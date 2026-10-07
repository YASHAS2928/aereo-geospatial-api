import asyncio
import hashlib
import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from app.body_limit import BodyLimitMiddleware
from app.config import Settings
from app.db import Feature, UploadedFile, database
from app.errors import InputError
from app.schemas import FileInfo, MeasurementPage

logger = logging.getLogger("aereo.api")


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    engine, sessions = database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        app.state.active = 0
        yield
        engine.dispose()

    app = FastAPI(title="Geospatial File Measurement API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.upload_bytes + 65536)
    app.state.engine = engine

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        started = time.monotonic()
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > settings.upload_bytes + 65536):
            response = error_response(request, "UPLOAD_LIMIT", "Request body exceeds limit", 413)
        else:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception(
                    "Unhandled request failure request_id=%s", request.state.request_id
                )
                response = error_response(request, "INTERNAL_ERROR", "Internal server error", 500)
        response.headers["X-Request-ID"] = request.state.request_id
        logger.info(
            "request_id=%s method=%s status=%s duration_ms=%.1f",
            request.state.request_id,
            request.method,
            response.status_code,
            (time.monotonic() - started) * 1000,
        )
        return response

    @app.exception_handler(InputError)
    async def input_error(request, exc):
        return error_response(request, exc.code, exc.message, exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error_response(request, "INVALID_REQUEST", "Invalid request parameters", 422)

    def require_file(session, file_id):
        result = session.get(UploadedFile, str(file_id))
        if not result:
            raise InputError("FILE_NOT_FOUND", "File not found", 404)
        return result

    def file_info(row):
        return {
            "id": row.id,
            "filename": row.filename,
            "feature_count": row.feature_count,
            "crs": row.crs,
            "status": row.status,
            "measured_count": row.measured_count,
            "skipped_count": row.feature_count - row.measured_count,
            "checksum_sha256": row.checksum,
            "size_bytes": row.size_bytes,
            "created_at": row.created_at.isoformat(),
        }

    @app.get("/health", tags=["operations"])
    def health():
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.post("/api/files/", status_code=201, tags=["files"], response_model=FileInfo)
    async def upload(file: UploadFile = File(...), source_crs: str | None = Form(None)):
        filename = (file.filename or "upload").replace("\\", "/").rsplit("/", 1)[-1][:255]
        extension = Path(filename).suffix.lower()
        if extension not in (".zip", ".kml"):
            raise InputError("UNSUPPORTED_FORMAT", "Upload a .zip Shapefile or .kml", 415)
        if app.state.active >= settings.concurrent_jobs:
            raise InputError("CAPACITY_EXCEEDED", "Processing capacity exhausted; retry later", 503)
        app.state.active += 1
        try:
            with TemporaryDirectory(prefix="aereo-upload-") as folder:
                path = Path(folder) / ("input" + extension)
                digest, size = hashlib.sha256(), 0
                with path.open("wb") as target:
                    while chunk := await file.read(64 * 1024):
                        size += len(chunk)
                        if size > settings.upload_bytes:
                            raise InputError("UPLOAD_LIMIT", "Upload exceeds byte limit", 413)
                        digest.update(chunk)
                        target.write(chunk)
                if not size:
                    raise InputError("EMPTY_UPLOAD", "File is empty")
                job_input, job_output = Path(folder) / "job.json", Path(folder) / "result.json"
                job_input.write_text(
                    json.dumps(
                        {
                            "path": str(path),
                            "extension": extension,
                            "source_crs": source_crs,
                            "settings": asdict(settings),
                        }
                    )
                )
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "app.worker",
                    str(job_input),
                    str(job_output),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=None,
                )
                try:
                    await asyncio.wait_for(process.wait(), settings.timeout_seconds)
                    if process.returncode != 0 or not job_output.exists():
                        raise InputError("PROCESSING_FAILED", "Worker failed", 500)
                    result = json.loads(job_output.read_text())
                    if "error" in result:
                        error = result["error"]
                        raise InputError(error["code"], error["message"], error["status"])
                    crs, records = result["crs"], result["features"]
                except TimeoutError as exc:
                    raise InputError(
                        "PROCESSING_TIMEOUT", "Processing time limit exceeded", 422
                    ) from exc
                finally:
                    if process.returncode is None:
                        process.kill()
                    await process.wait()
                measured = sum(r["measurement_status"] == "MEASURED" for r in records)
                warnings = any(
                    r["measurement_status"] not in ("MEASURED", "NOT_APPLICABLE") for r in records
                )
                row = UploadedFile(
                    id=str(uuid.uuid4()),
                    filename=filename,
                    checksum=digest.hexdigest(),
                    size_bytes=size,
                    crs=crs,
                    status="COMPLETED_WITH_WARNINGS" if warnings else "COMPLETED",
                    feature_count=len(records),
                    measured_count=measured,
                )

                def persist():
                    with sessions.begin() as session:
                        session.add(row)
                        session.flush()
                        session.add_all(
                            Feature(file_id=row.id, index=r["index"], data=r) for r in records
                        )
                    return file_info(row)

                return await asyncio.to_thread(persist)
        finally:
            app.state.active -= 1
            await file.close()

    @app.get("/api/files/{file_id}/", tags=["files"], response_model=FileInfo)
    def information(file_id: uuid.UUID):
        with sessions() as session:
            return file_info(require_file(session, file_id))

    @app.get("/api/files/{file_id}/measurements/", tags=["files"], response_model=MeasurementPage)
    def measurements(
        file_id: uuid.UUID, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)
    ):
        with sessions() as session:
            row = require_file(session, file_id)
            features = session.scalars(
                select(Feature)
                .where(Feature.file_id == row.id)
                .order_by(Feature.index)
                .offset(offset)
                .limit(limit)
            ).all()
            return {
                "file_id": row.id,
                "count": row.feature_count,
                "next_offset": offset + limit if offset + limit < row.feature_count else None,
                "features": [feature.data for feature in features],
            }

    return app


def error_response(request, code, message, status):
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": message},
            "request_id": request.state.request_id,
        },
    )


app = create_app()

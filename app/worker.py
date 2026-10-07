import asyncio
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from app.config import Settings
from app.errors import InputError


async def run_job(path: Path, source_crs: str | None, settings: Settings):
    job_input, job_output = path.parent / "job.json", path.parent / "result.json"
    job_input.write_text(
        json.dumps(
            {
                "path": str(path),
                "extension": path.suffix,
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
        return result["crs"], result["features"]
    except TimeoutError as exc:
        raise InputError("PROCESSING_TIMEOUT", "Processing time limit exceeded", 422) from exc
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()


def main():
    from app.processing import process_file

    payload = json.loads(Path(sys.argv[1]).read_text())
    try:
        crs, features = process_file(
            payload["path"],
            payload["extension"],
            payload["source_crs"],
            Settings(**payload["settings"]),
        )
        result = {"crs": crs, "features": features}
    except InputError as exc:
        result = {"error": {"code": exc.code, "message": exc.message, "status": exc.status}}
    except Exception:
        logging.exception("Unexpected processing failure")
        result = {
            "error": {"code": "PROCESSING_FAILED", "message": "Processing failed", "status": 500}
        }
    Path(sys.argv[2]).write_text(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()

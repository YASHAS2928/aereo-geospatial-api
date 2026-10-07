# Geospatial File Measurement API

FastAPI backend for the Aereo assignment. Upload a zipped Shapefile or KML, then retrieve its features, polygon areas in square metres and line lengths in metres. Points are stored with no measurement.

## Run locally

The verified runtime is Python 3.12. Docker Compose starts the API and PostgreSQL 16, and applies database migrations:

```bash
docker compose up --build
```

Open [Swagger UI](http://localhost:8000/docs) to upload a sample and try the endpoints. [Health](http://localhost:8000/health) checks the database connection. Sample files are in `examples/`.

For SQLite development without Docker:

```bash
python -m venv .venv
```

Activate with `source .venv/bin/activate` on Linux/macOS or `.venv\Scripts\Activate.ps1` in Windows PowerShell. Then run:

```bash
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps -e .
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

For PostgreSQL without Compose, export `DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/database` before migration and startup. `.env.example` lists the settings; the app reads environment variables and does not load that file automatically. Compose credentials are demo defaults. The API has no authentication and is intended for local review.

## Try the API

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/files/` | Upload and process a `.zip` Shapefile or `.kml` |
| GET | `/api/files/{id}/` | Retrieve persisted file information |
| GET | `/api/files/{id}/measurements/` | Retrieve features and measurements |

Upload either supplied sample. Use `curl.exe` in Windows PowerShell:

```bash
curl -fsS -F 'file=@examples/survey.kml' http://localhost:8000/api/files/
curl -fsS -F 'file=@examples/survey.zip' http://localhost:8000/api/files/
```

The KML upload returns HTTP 201. This response is from the checked-in sample run; new uploads receive a new UUID and timestamp. The checksum depends on the file bytes:

```json
{
  "id": "ca123ae5-e331-44f6-b98a-0ad4b0e7086b",
  "filename": "survey.kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "measured_count": 2,
  "skipped_count": 1,
  "checksum_sha256": "1be5689b05167332978604e0ff21d4ad8d8df23c2994b0e0daab9c63e3e4a488",
  "size_bytes": 653,
  "created_at": "2026-10-07T18:19:31.666621Z"
}
```

Replace `RETURNED_UUID` with the ID from your upload:

```bash
curl -fsS http://localhost:8000/api/files/RETURNED_UUID/
curl -fsS 'http://localhost:8000/api/files/RETURNED_UUID/measurements/?limit=100&offset=0'
```

File information returns the same metadata with HTTP 200. Measurements return HTTP 200 with `file_id`, total `count`, `next_offset` and `features`. Pagination defaults to 100 features, with a maximum of 500. This is the complete Point feature from the sample response:

```json
{
  "index": 2,
  "source_id": "marker-1",
  "geometry_type": "Point",
  "geometry": {"type": "Point", "coordinates": [77.59, 12.97]},
  "source_geometry_xml": null,
  "properties": {},
  "source_crs": "EPSG:4326",
  "measurement_status": "NOT_APPLICABLE",
  "measurement_type": null,
  "value": null,
  "unit": null,
  "measurement_crs": null,
  "warning_code": null
}
```

The same sample contains a polygon of approximately **12,003.11 m²** and a line of approximately **154.95 m**. Stored values are not rounded. See [the full response](examples/sample-response.json) for their geometry, attributes and projected CRS WKT, or [OpenAPI](examples/openapi.json) for the response schemas.

A Shapefile ZIP must contain one dataset with matching `.shp`, `.shx` and `.dbf` components. If its CRS is absent, supply it explicitly:

```bash
curl -fsS -F 'file=@survey-without-prj.zip' -F 'source_crs=EPSG:4326' http://localhost:8000/api/files/
```

KML always uses WGS84 and rejects overrides. Invalid uploads return an error code and message: 413 for size limits, 415 for unsupported formats, 422 for invalid files/parameters, 404 for missing files and 503 when processing capacity is full. Unexpected failures return a sanitized 500. Request IDs link responses to logs.

## Structure and processing flow

| File | Responsibility |
|---|---|
| `app/main.py` | Endpoints, upload admission and database transaction |
| `app/worker.py` | Start, time out and clean up a processing subprocess; worker entry point |
| `app/processing.py` | Extract features, check coordinate limits and attach measurements |
| `app/geo/readers.py` | ZIP validation, Fiona Shapefile reader and restricted KML parser |
| `app/geo/measurement.py` | Validate geometry, project it and calculate area or length |
| `app/db.py`, `migrations/` | SQLAlchemy models and Alembic schema |
| `app/schemas.py`, `app/body_limit.py` | Response models and request-body limit |

An upload is saved in a temporary directory. The worker reads features and measures supported geometries. One transaction stores the file metadata and all feature records. Temporary files are then removed. Retrieval reads those stored records; uploading the same file again creates a separate ID.

Original feature IDs, geometry types, coordinates, CRS and attributes are retained. Unsupported or invalid geometries produce a per-feature status and null measurement; valid features still succeed. A file-level failure stores no partial result.

## CRS and design decisions

Geographic degrees are never used directly for area or length. Each supported feature is transformed to WGS84, then to a local projected CRS centred on its bounds. Polygons use Lambert azimuthal equal-area; lines use azimuthal equidistant. Shapely measures the projected geometry in metres. Geographic edges are subdivided before projection; polygon holes subtract from area and multi-geometries sum their parts.

| Decision | Reason and alternative |
|---|---|
| Feature-local projections | A single file can span UTM zones. EPSG:3857 has unsuitable metric distortion. |
| SQLAlchemy with PostgreSQL | Persist metadata and feature JSON. PostGIS is unnecessary for these endpoints because there are no spatial queries. SQLite supports local development. |
| One subprocess per upload | A timed-out native GIS task can be killed. A thread timeout would leave it running. The cost is process startup per upload. |
| Explicit geometry statuses | Preserve problematic features for inspection; silently repairing topology could change their meaning. |
| Restricted ZIP/XML readers | Reject traversal, excessive expansion, XML entities and remote references before accepting a result. |

Defaults: 10 MiB upload, 50 MiB expanded ZIP, 10,000 features, 500,000 input vertices, 30-second deadline and two processing jobs per server process. Limits are in `app/config.py`.

Measurements are horizontal 2D. Altitude is retained but not measured. Features spanning more than six degrees or crossing the antimeridian are flagged. The line projection preserves distances from its centre, not every arbitrary segment; the extent limit is not a certified accuracy tolerance. This is a local-survey implementation, with limited KML geometry support. It has no global admission control, authentication or durable job queue. [DESIGN.md](DESIGN.md) explains these boundaries and the projection references in detail.

## Validation, learning and future scope

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m alembic check
```

Use a disposable database for tests: integration fixtures create and drop application tables. Set `TEST_DATABASE_URL` to test PostgreSQL. CI checks both databases, migrations and a clean Docker Compose workflow with both sample formats. [VERIFICATION.md](VERIFICATION.md) records the runs and requirement review.

The tests compare measurements with independent ellipsoidal references, a known 10,000 m² square and a 5 m line. They also exercise malformed inputs, archive attacks, timeout cleanup, concurrent uploads and transaction rollback.

Concrete implementation lessons:

- Projection choice depends on the measurement: area and length have different distortion requirements.
- Timing out a task is insufficient unless the underlying worker stops.
- Successful inserts do not prove atomicity; the rollback test deliberately fails a feature write.
- The first clean Docker run failed because Fiona needed `libexpat.so.1`. Installing `libexpat1` and checking GIS imports during the build fixed it.

Next steps would be explicit geodesic/source-CRS edge semantics, antimeridian support and broader KML geometry handling. A deployed service would also need authentication, global request limits and a durable queue for larger jobs.

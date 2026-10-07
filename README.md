# Geospatial File Measurement API

A FastAPI service that accepts zipped Shapefiles and KML, persists extracted features, and returns horizontal polygon areas and line lengths in metric units.

The implementation prioritizes explicit measurement semantics, isolated file-processing failures and reproducible review. It is a bounded synchronous service for local surveys, not a claim of a globally accurate surveying system.

## Quick start

Python 3.12 is the verified runtime. Docker Compose uses PostgreSQL 16:

```bash
docker compose up --build
```

API documentation: http://localhost:8000/docs
Health: http://localhost:8000/health

Compose credentials are local demonstration defaults. Do not expose this unauthenticated service directly to the internet. For a deployed demonstration, place it behind access control and request/concurrency limits.

Without Docker (SQLite development mode):

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell instead: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps -e .
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

For PostgreSQL, set `DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/database` before migration and server startup. SQLite is a local convenience; Compose and CI target PostgreSQL. `.env.example` documents variables; the application reads exported environment variables, not a .env file automatically.

## Review in five minutes

1. Run setup and upload `examples/survey.kml` or `examples/survey.zip`.
2. Retrieve the file and measurements using the returned UUID.
3. Observe that Point records are retained with a null measurement, not zero.
4. Inspect `app/geo/measurement.py` and `tests/test_measurement.py` for projection decisions and independent ellipsoidal test oracles.
5. Run `python -m pytest -q` and review negative-input/rollback tests.

## API

### Upload

```bash
curl -fsS -F 'file=@examples/survey.kml' http://localhost:8000/api/files/
curl -fsS -F 'file=@examples/survey.zip' http://localhost:8000/api/files/
# Only when a Shapefile has no usable projection definition:
curl -fsS -F 'file=@survey-without-prj.zip' -F 'source_crs=EPSG:4326' http://localhost:8000/api/files/
```

Returns **201**, after processing and a successful database transaction:

```json
{
  "id": "<returned UUID>",
  "filename": "survey.kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "measured_count": 2,
  "skipped_count": 1,
  "checksum_sha256": "<computed SHA-256>",
  "size_bytes": 0,
  "created_at": "<timestamp>"
}
```

This is an illustrative response shape; `size_bytes`, timestamps and IDs are populated from the actual upload. `examples/sample-response.json` contains an actual verified run.

### File information

```bash
curl -fsS http://localhost:8000/api/files/RETURNED_UUID/
```

Returns the same persisted metadata. A missing UUID returns 404. Invalid UUID syntax returns 422.

### Measurements

```bash
curl -fsS 'http://localhost:8000/api/files/RETURNED_UUID/measurements/?limit=100&offset=0'
```

Returns `file_id`, total `count`, nullable `next_offset`, and `features` in stable index order. Default limit is 100, maximum 500. Each feature includes source ID, index, geometry type, geometry, source CRS, properties, measurement status/type/value/unit and measurement CRS WKT. Original coordinate geometry is explicitly labelled with its source CRS: it is not advertised as RFC 7946 GeoJSON when projected input is preserved.

Measurement units are `m` and `m2`. Original altitude is retained where supplied; measurement is horizontal 2D. No rounding is applied to stored values. Numeric precision is not a claim of equivalent positional accuracy.

| Status | Meaning |
|---|---|
| MEASURED | Projected area or length calculated |
| NOT_APPLICABLE | Point or MultiPoint: no measurement required |
| EMPTY_GEOMETRY | Empty or missing geometry |
| INVALID_GEOMETRY | Invalid topology; reason returned |
| UNSUPPORTED_GEOMETRY | GeometryCollection: retained but not measured |
| INVALID_OR_UNSUPPORTED_GEOMETRY | Malformed or unsupported KML geometry |
| UNSUPPORTED_CRS_EXTENT | Feature exceeds the documented local projection domain or densification budget |
| TRANSFORMATION_FAILED | Cannot safely transform the feature |

Individual feature warnings produce `COMPLETED_WITH_WARNINGS`; good features remain available. Unsupported/invalid measurements are null. A valid zero-length geometry can produce zero. A malformed file returns an error and publishes no partial database rows.

| HTTP code | Examples |
|---|---|
| 413 | Upload, archive expansion, feature or coordinate limit |
| 415 | Unsupported file extension |
| 422 | Invalid XML, corrupt Shapefile/ZIP, missing CRS, ambiguous dataset, timeout |
| 404 | File not found |
| 503 | Per-server processing capacity exhausted; retry later |
| 500 | Unexpected worker or database failure; sanitized response |

Errors include `error.code`, `error.message` and a request ID. Responses include `X-Request-ID` for log correlation.

## Architecture

```mermaid
flowchart TD
    A[Upload and body limit] --> B[Temporary file and checksum]
    B --> C[Isolated processing subprocess]
    C --> D[Safe reader and feature extraction]
    D --> E[Per-feature projection and measurement]
    E --> F[Atomic database transaction]
    F --> G[Metadata and paginated retrieval]
```

- `app/main.py`: HTTP contracts, capacity admission, worker deadline and persistence.
- `app/worker.py`: one subprocess per job; JSON result/error transport.
- `app/geo/readers.py`: bounded ZIP extraction, Fiona Shapefile reading and restricted KML parsing.
- `app/geo/measurement.py`: pure projection/measurement policy.
- `app/db.py`, `migrations/`: SQLAlchemy models and Alembic schema.
- `app/schemas.py`: typed responses, reflected in OpenAPI.

A fresh subprocess costs startup time, but provides a killable deadline and avoids one malformed GIS job taking down another. It communicates via temporary JSON rather than pickled custom exceptions. Uploads have independent temporary directories, always cleaned during normal error/timeout handling. Abrupt whole-host termination may leave temporary directories; a deployment should apply an age-based cleanup policy.

Database writes execute in a thread outside the event loop. One transaction inserts file and features. Unique `(file_id,index)` and foreign keys enforce identity. Raw uploads are discarded after processing; metadata, checksum and extracted records persist. Repeated uploads receive separate IDs. PostgreSQL JSON storage suffices because the API does not perform spatial querying; PostGIS would add no value to these endpoints.

## Projection policy

1. KML uses WGS84 longitude/latitude. Shapefile uses its projection definition, with an explicit caller override only when CRS is absent. Coordinates are never guessed from their magnitude.
2. PyProj transforms source geometry to WGS84 using `always_xy=True`, error checking and `allow_ballpark=False`. Remote grid downloading is disabled; unavailable datum operations become explicit failures.
3. Each feature receives a projected CRS centred on its longitude/latitude bounding box midpoint. Polygon/MultiPolygon uses **Lambert azimuthal equal-area**; LineString/MultiLineString uses **azimuthal equidistant**. Measurements then use Shapely in metres.
4. Geographic straight edges are densified to at most 0.01 degrees before projection, with a precomputed one-million-vertex ceiling. Multi geometries sum their parts; polygon holes subtract from area. No automatic topology repair.
5. Supported longitude and latitude spans are each at most 6 degrees. Ordinary zone/equator crossings work. Antimeridian crossings and broader features are flagged instead of returning misleading numbers.

Why not a single UTM CRS? One file can contain distant features, and zone boundaries are arbitrary for small cross-boundary surveys. Why not EPSG:3857? Its area and distance distortions are unsuitable for a general metric measurement API. Why not use ellipsoidal area alone? The assignment specifically requires a projected calculation. Independent geodesic methods are used as test references.

**Limitations:** equidistant projections preserve distance from their centre, not every arbitrary segment. Densified edges follow straight interpolation in WGS84 coordinate space, not a universal geodesic-edge or original-CRS curved-edge model. Six-degree bounding limits bound domain, not a certified error tolerance. Supplied datum accuracy, sparse geometry and survey quality affect results. The tests establish numeric tolerances for specific local fixtures, not survey-grade global guarantees. Curved geometries, mixed collections and broader extents require an expanded policy.

References: [PyProj transformations](https://pyproj4.github.io/pyproj/stable/api/transformer.html), [PROJ projections](https://proj.org/en/stable/operations/projections/index.html), [GDAL Shapefile driver](https://gdal.org/en/stable/drivers/vector/shapefile.html).

## Input handling and limits

Defaults in `Settings`: 10 MiB upload; 50 MiB expanded ZIP; 100 archive members; 10,000 features; 500,000 input vertices; 30-second processing deadline; two simultaneous processing jobs **per server process**.

The request-body guard counts actual bytes, including chunked bodies, before multipart parsing. It buffers at most upload limit plus 64 KiB of multipart overhead. This means the HTTP layer uses bounded memory rather than pretending to offer unlimited streaming. A reverse proxy/global admission policy remains necessary under large numbers of simultaneous slow clients.

ZIP rejects traversal/absolute paths, symlinks, encryption, normalized duplicate/case-colliding names and excessive expansion. Exactly one matched `.shp/.shx/.dbf` dataset is accepted, including nested folders. `.prj` is required unless CRS is explicitly supplied; `.cpg` is optional. Malformed or conflicting CRS is an error.

KML supports nested folders/documents, Placemark IDs, Point, LineString, Polygon with holes, MultiGeometry, name/description and ExtendedData. XML entities/DTDs are blocked. NetworkLink is rejected and never fetched. Unsupported gx:Track/Model returns a feature warning. It is deliberately a restricted KML reader, not a complete implementation of rendering/style/remote-resource behavior.

## Tests and CI

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m alembic check
# Existing disposable PostgreSQL database:
TEST_DATABASE_URL=postgresql+psycopg://user:password@localhost/db python -m pytest -q
```

**Use a disposable test database:** integration fixtures create/drop application tables.

Tests cover independent ellipsoidal area/length comparisons, holes, feet-based projected input, both hemispheres, UTM/equator boundary crossings, explicit geometry statuses, real Shapefile round-trip, malformed inputs, ZIP path attacks/expansion/symlinks, XML entities, feature limits, upload size, worker timeout/capacity, persistence across app restarts, pagination and transaction rollback on injected database failure.

GitHub Actions defines SQLite tests, PostgreSQL migrations/tests and a separate Docker Compose end-to-end job. A checked-in workflow is not evidence it has run: see `VERIFICATION.md` for actual local results and outstanding checks.

## Learning and future scope

Implementation findings:

- Measurement CRS should reflect the measurement type; equal-area and distance-oriented projections have different guarantees.
- Custom exceptions crossing process boundaries can fail to deserialize and turn expected validation errors into 500s. Explicit JSON errors avoid that failure mode.
- A timeout on a process-pool future does not stop a running GIS job. Independent subprocess lifecycle handling makes the deadline enforceable without killing unrelated jobs.
- Multipart parser file spooling does not itself enforce a whole-request byte limit. Raw ASGI body counting is required for clients without Content-Length.
- Transaction rollback must be verified by causing a write failure, not by merely checking a successful insert.

Future scope: geodesic/source-CRS edge semantics and densification policy; expanded/antimeridian projection support; per-tenant authorization; durable job queues for larger datasets; object storage retention; global rate/capacity limits; richer geometry support and operational metrics. These are tradeoffs to address at the relevant scale, not unfinished minimum requirements.

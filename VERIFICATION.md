# Verification record

Verified locally and on GitHub-hosted Linux runners, Python 3.12.

Passing hosted run: https://github.com/YASHAS2928/aereo-geospatial-api/actions/runs/37676684460

Last hosted verification before the worker/readability review: `49bd6f91ef686f7baf594c76997db0140a590252` (8 October 2026 IST).

| Check | Actual result |
|---|---|
| Fresh virtual environment installation | Passed |
| Unit/API integration tests against SQLite | 43 passed, one third-party Starlette/httpx deprecation warning |
| Independent geometry reference cases | Passed: geographic ellipsoidal references, known 10,000 m2 square, known 5 m line, holes, feet-based projected input |
| Concurrent uploads | Two independent successful records; third request returns 503 at configured capacity |
| Injected feature-write failure | File and feature transaction rolled back; sanitized 500 |
| Worker deadline | Stalled worker terminated and processing slot released |
| End-to-end supplied KML | 201, three features, two measurements |
| End-to-end supplied zipped Shapefile | 201, one feature, one measurement |
| Ruff lint and formatting | Passed |
| Alembic migration on blank SQLite | Passed |
| Alembic model/schema drift check | Passed |
| PostgreSQL migrations and tests | Passed in hosted CI run 37670360190: 43 tests and schema drift check |
| Docker image / Compose | Passed in hosted CI: clean build, native GIS imports, PostgreSQL-backed service startup |
| GitHub Actions | Both test and container jobs passed in run 37676684460 |
| Public GitHub publication | Published: https://github.com/YASHAS2928/aereo-geospatial-api |

## Release result

The engineering release gates have passed. Hosted container CI exercises both supplied file formats and retrieves polygon measurements. PostgreSQL migrations, schema drift checks and all 43 tests pass.

The first container run caught a missing Fiona native dependency (`libexpat.so.1`). The Dockerfile now installs `libexpat1` and verifies Fiona/Shapely/PyProj imports during image build. This was a runtime defect, fixed and independently verified in a clean container.

The repository is ready for technical submission review. The application form has not been submitted. Rehearse projection semantics, file-validation decisions and transaction rollback before interview. No selection guarantee, production-scale benchmark or survey-grade accuracy claim is made.

## Assignment requirement review

Reviewed against the supplied five-page **Geospatial File Measurement API** assignment on 8 October 2026 IST.

| Requirement | Implementation and evidence |
|---|---|
| 1. Django/DRF or FastAPI | FastAPI application and typed response models; `app/main.py`, `app/schemas.py` |
| 2. Shapefile ZIP and KML upload | `POST /api/files/`; both supplied formats exercised by container CI |
| 3. Feature ID/index, type, geometry, CRS, attributes; graceful unsupported geometry | Readers preserve source fields; processing attaches an index and explicit measurement status; reader/geometry tests |
| 4. Polygon area, LineString length, no Point measurement | Projected square metres/metres; Point fields are null; numeric reference and API tests |
| 5. Project geographic coordinates before measuring | Source CRS to WGS84 to feature-local LAEA/AEQD, then Shapely area/length; `app/geo/measurement.py` |
| 6. Upload, information and measurements APIs | All three required routes; upload/retrieval/pagination and invalid-parameter tests |
| 7. README setup, API examples, structure, flows, CRS, decisions/alternatives | README includes each item and actual sample output; DESIGN.md provides additional detail |
| 8. Public repo, learning and future scope | Public repository; README contains concrete findings and next steps |

### Complexity review

The subprocess boundary is retained because native GIS work needs an enforceable deadline. The upload endpoint now delegates that lifecycle to `app/worker.py`; it still owns upload validation and the database transaction. No queue, service/repository framework or extra infrastructure was added. Atomic writes, byte limits and safe ZIP/XML handling remain because they address specific failure modes exercised by tests.

The API is a bounded local-survey implementation. It does not provide authentication, global capacity control, broad KML support or certified measurement accuracy. The six-degree projection domain is documented. Passing tests do not establish candidate understanding or production readiness. The application form remains unsubmitted.

Local checks after the worker/readability review: 43 tests passed; Ruff lint and formatting passed; Alembic reported no schema drift. Push-triggered CI checks the published revision separately.

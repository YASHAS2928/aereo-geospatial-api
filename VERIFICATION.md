# Verification record

Verified locally and on GitHub-hosted Linux runners, Python 3.12.

Passing hosted run: https://github.com/YASHAS2928/aereo-geospatial-api/actions/runs/37670721763

Verified implementation commit: `68352b7e1d78ac394a6fbf15aac86b84a033f41f` (8 October 2026 IST).

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
| GitHub Actions | Both test and container jobs passed in run 37670721763 |
| Public GitHub publication | Published: https://github.com/YASHAS2928/aereo-geospatial-api |

## Release result

The engineering release gates have passed. Hosted container CI exercises both supplied file formats and retrieves polygon measurements. PostgreSQL migrations, schema drift checks and all 43 tests pass.

The first container run caught a missing Fiona native dependency (`libexpat.so.1`). The Dockerfile now installs `libexpat1` and verifies Fiona/Shapely/PyProj imports during image build. This was a runtime defect, fixed and independently verified in a clean container.

The repository is ready for technical submission review. The application form has not been submitted. Rehearse projection semantics, file-validation decisions and transaction rollback before interview. No selection guarantee, production-scale benchmark or survey-grade accuracy claim is made.

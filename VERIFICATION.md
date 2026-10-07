# Verification record

Executed on 2026-10-07, Python 3.12, Linux.

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
| PostgreSQL local runtime | Not verified: this execution environment cannot launch PostgreSQL under a non-root mapped user |
| Docker image / Compose | Not verified: Docker runtime unavailable here |
| GitHub Actions | Workflow authored; no hosted execution yet |
| Public GitHub publication | Pending |

## Release gate

Before sending the assignment link, run the PostgreSQL and container jobs in the provided GitHub Actions workflow. Fix failures and preserve the passing run link. Verify both upload formats through the hosted or container service and rehearse a short explanation of projection policy, error isolation and rollback.

The source package implements the minimum API and documented local-survey measurement policy. It is not labelled submission-ready until the outstanding database/container checks pass. No selection guarantee, production-scale benchmark or survey-grade accuracy claim is made.

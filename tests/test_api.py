import os
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db import Base, UploadedFile
from app.main import create_app


@pytest.fixture
def application(tmp_path):
    settings = replace(
        Settings(), database_url=os.getenv("TEST_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    yield app
    Base.metadata.drop_all(app.state.engine)


def test_upload_retrieve_paginate(application):
    with TestClient(application) as client:
        data = Path("examples/survey.kml").read_bytes()
        response = client.post("/api/files/", files={"file": ("survey.kml", data)})
        assert response.status_code == 201, response.text
        info = response.json()
        assert info["feature_count"] == 3
        assert info["measured_count"] == 2
        assert info["created_at"].endswith("Z")
        assert client.get(f"/api/files/{info['id']}/").json() == info
        page = client.get(f"/api/files/{info['id']}/measurements/?limit=2").json()
        assert page["next_offset"] == 2
        assert page["features"][0]["value"] > 0
        assert page["features"][0]["properties"]["owner"] == "Demo"
    with TestClient(application) as client:
        assert client.get(f"/api/files/{info['id']}/").json() == info


@pytest.mark.parametrize(
    "filename,data,code",
    [("a.txt", b"x", 415), ("a.kml", b"", 422), ("a.kml", b"<bad", 422), ("a.zip", b"bad", 422)],
)
def test_bad_uploads(application, filename, data, code):
    with TestClient(application) as client:
        response = client.post("/api/files/", files={"file": (filename, data)})
        assert response.status_code == code, response.text
        assert response.json()["error"]["code"]
        assert response.headers["x-request-id"]
    with application.state.engine.connect() as connection:
        assert not connection.execute(select(UploadedFile.id)).all()


def test_missing_and_invalid_parameters(application):
    with TestClient(application) as client:
        assert client.get(f"/api/files/{uuid.uuid4()}/").status_code == 404
        assert client.get("/api/files/not-a-uuid/").status_code == 422
        assert client.post("/api/files/").status_code == 422
        assert client.get(f"/api/files/{uuid.uuid4()}/measurements/?limit=1000").status_code == 422
        assert client.get("/health").status_code == 200


def test_upload_limit_without_content_length(tmp_path):
    app = create_app(
        replace(Settings(), database_url=f"sqlite:///{tmp_path}/limit.db", upload_bytes=10)
    )
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as client:
        response = client.post("/api/files/", files={"file": ("a.kml", b"x" * 100)})
        assert response.status_code == 413
        response = client.post(
            "/api/files/",
            content=iter([b"x" * 70000]),
            headers={"Content-Type": "multipart/form-data; boundary=a"},
        )
        assert response.status_code == 413


def test_worker_timeout(tmp_path):
    app = create_app(
        replace(Settings(), database_url=f"sqlite:///{tmp_path}/timeout.db", timeout_seconds=0)
    )
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as client:
        response = client.post("/api/files/", files={"file": ("a.kml", b"<kml/>")})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "PROCESSING_TIMEOUT"
        assert app.state.active == 0


def test_database_failure_is_atomic(application):
    from sqlalchemy import event

    def fail_feature(mapper, connection, target):
        raise RuntimeError("forced database write failure")

    from app.db import Feature

    event.listen(Feature, "before_insert", fail_feature)
    try:
        with TestClient(application) as client:
            response = client.post(
                "/api/files/",
                files={"file": ("survey.kml", Path("examples/survey.kml").read_bytes())},
            )
            assert response.status_code == 500
            assert "forced" not in response.text
        with application.state.engine.connect() as connection:
            assert not connection.execute(select(UploadedFile.id)).all()
    finally:
        event.remove(Feature, "before_insert", fail_feature)


def test_capacity_returns_retryable_failure(application):
    with TestClient(application) as client:
        application.state.active = 2
        response = client.post("/api/files/", files={"file": ("a.kml", b"<kml/>")})
        assert response.status_code == 503
        application.state.active = 0


def test_concurrent_jobs_have_independent_ids(application):
    import asyncio

    import httpx

    async def check():
        async with application.router.lifespan_context(application):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url="http://test"
            ) as client:
                data = Path("examples/survey.kml").read_bytes()
                results = await asyncio.gather(
                    *(
                        client.post("/api/files/", files={"file": ("survey.kml", data)})
                        for _ in range(3)
                    )
                )
                assert sorted(r.status_code for r in results) == [201, 201, 503]
                ids = [r.json()["id"] for r in results if r.status_code == 201]
                assert len(set(ids)) == 2
                assert application.state.active == 0

    asyncio.run(check())

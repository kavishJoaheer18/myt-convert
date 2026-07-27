"""API surface: upload, poll, download.

The app is pointed at a temporary SQLite database and data directory before it is
imported, so the routes are exercised for real without Postgres or a broker.  The
Celery dispatch is replaced by a direct call, which is what the worker does
anyway — only the transport differs.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

_TMP_ROOT = Path(tempfile.mkdtemp(prefix="gridlock_api_"))
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{(_TMP_ROOT / 'test.db').as_posix()}"
os.environ["DATA_DIR"] = str(_TMP_ROOT / "data")

# Imported after the environment is set: the engine is built at import time.
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.models.db import JobStatus, init_db  # noqa: E402
from app.services import run_conversion  # noqa: E402
from tests.fixtures.catalog import get_fixture  # noqa: E402


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    init_db()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def synchronous_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the conversion inline instead of handing it to Celery."""
    import app.worker as worker_module

    class _Inline:
        @staticmethod
        def delay(job_id: str) -> None:
            run_conversion(job_id)

    monkeypatch.setattr(worker_module, "convert_job", _Inline)


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_upload_convert_and_download(
    client: TestClient, synchronous_worker: None
) -> None:
    fixture = get_fixture("simple_table")

    with fixture.pdf_path.open("rb") as handle:
        created = client.post(
            "/jobs", files={"file": ("simple_table.pdf", handle, "application/pdf")}
        )
    assert created.status_code == 202, created.text
    job_id = created.json()["id"]

    detail = client.get(f"/jobs/{job_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == JobStatus.DONE
    assert body["page_count"] == 1
    assert body["cell_count"] == 24
    assert body["has_output"] is True

    download = client.get(f"/jobs/{job_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith(
        "application/vnd.openxmlformats"
    )
    # A real .xlsx is a zip archive.
    assert download.content[:2] == b"PK"

    sheet = client.get(f"/jobs/{job_id}/sheets/1")
    assert sheet.status_code == 200
    assert len(sheet.json()["cells"]) == 24


def test_rejects_non_pdf(client: TestClient) -> None:
    response = client.post(
        "/jobs", files={"file": ("notes.txt", b"hello", "text/plain")}
    )

    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]


def test_rejects_empty_upload(client: TestClient) -> None:
    response = client.post("/jobs", files={"file": ("empty.pdf", b"", "application/pdf")})

    assert response.status_code == 400


def test_unknown_job_is_404(client: TestClient) -> None:
    assert client.get("/jobs/does-not-exist").status_code == 404


def test_download_before_completion_conflicts(client: TestClient) -> None:
    """A queued job has no workbook yet, and must say so rather than 404."""
    from app.models.db import Job, SessionLocal

    session = SessionLocal()
    job = Job(filename="pending.pdf", status=JobStatus.QUEUED)
    session.add(job)
    session.commit()
    job_id = job.id
    session.close()

    response = client.get(f"/jobs/{job_id}/download")
    assert response.status_code == 409

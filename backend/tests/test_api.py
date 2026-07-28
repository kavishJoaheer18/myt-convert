"""API surface: upload, poll, download.

The app runs against the temporary SQLite database configured in conftest, and
Celery dispatch is replaced by a direct call — which is what the worker does
anyway, only the transport differs.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.models.db import JobStatus
from tests.fixtures.catalog import get_fixture


def test_health(api_client: TestClient) -> None:
    response = api_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_upload_convert_and_download(
    api_client: TestClient, synchronous_worker: None
) -> None:
    fixture = get_fixture("simple_table")

    with fixture.pdf_path.open("rb") as handle:
        created = api_client.post(
            "/jobs", files={"file": ("simple_table.pdf", handle, "application/pdf")}
        )
    assert created.status_code == 202, created.text
    job_id = created.json()["id"]

    detail = api_client.get(f"/jobs/{job_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == JobStatus.DONE
    assert body["page_count"] == 1
    assert body["cell_count"] == 24
    assert body["has_output"] is True

    download = api_client.get(f"/jobs/{job_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith(
        "application/vnd.openxmlformats"
    )
    # A real .xlsx is a zip archive.
    assert download.content[:2] == b"PK"

    sheet = api_client.get(f"/jobs/{job_id}/sheets/1")
    assert sheet.status_code == 200
    assert len(sheet.json()["cells"]) == 24


def test_page_image_is_rendered_for_review(
    api_client: TestClient, synchronous_worker: None
) -> None:
    fixture = get_fixture("simple_table")
    with fixture.pdf_path.open("rb") as handle:
        job_id = api_client.post(
            "/jobs", files={"file": ("page_image.pdf", handle, "application/pdf")}
        ).json()["id"]

    response = api_client.get(f"/jobs/{job_id}/pages/1/image")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_rejects_non_pdf(api_client: TestClient) -> None:
    response = api_client.post(
        "/jobs", files={"file": ("notes.txt", b"hello", "text/plain")}
    )

    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]


def test_rejects_empty_upload(api_client: TestClient) -> None:
    response = api_client.post(
        "/jobs", files={"file": ("empty.pdf", b"", "application/pdf")}
    )

    assert response.status_code == 400


def test_unknown_job_is_404(api_client: TestClient) -> None:
    assert api_client.get("/jobs/does-not-exist").status_code == 404


def test_download_before_completion_conflicts(api_client: TestClient) -> None:
    """A queued job has no workbook yet, and must say so rather than 404."""
    from app.models.db import Job, new_session

    session = new_session()
    job = Job(filename="pending.pdf", status=JobStatus.QUEUED)
    session.add(job)
    session.commit()
    job_id = job.id
    session.close()

    response = api_client.get(f"/jobs/{job_id}/download")
    assert response.status_code == 409

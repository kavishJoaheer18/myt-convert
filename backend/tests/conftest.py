"""Shared test wiring.

The test database and data directory are configured here, before anything
imports application code, because settings are cached process-wide and the
engine is built from them. Doing it in an individual test module would work only
for whichever module pytest happened to import first.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

_TMP_ROOT = Path(tempfile.mkdtemp(prefix="gridlock_tests_"))
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{(_TMP_ROOT / 'test.db').as_posix()}"
os.environ["DATA_DIR"] = str(_TMP_ROOT / "data")
# Consensus is exercised with explicit test doubles; it must not fire on its own
# during unrelated API tests.
os.environ["ENABLE_CONSENSUS"] = "false"

from tests.accuracy import AccuracyReport, format_summary  # noqa: E402

#: Reports collected by every phase's tests, printed once the session ends.
_REPORTS: dict[str, list[AccuracyReport]] = {}


def record_report(phase: str, report: AccuracyReport) -> None:
    _REPORTS.setdefault(phase, []).append(report)


def paddle_available() -> bool:
    """Whether the OCR stack is installed in this environment."""
    try:
        import paddleocr  # noqa: F401
    except ImportError:
        return False
    return True


requires_ocr = pytest.mark.skipif(
    not paddle_available(),
    reason="PaddleOCR is not installed; install requirements-ocr.txt to run the OCR gate",
)


@pytest.fixture(scope="session")
def ocr_engine():
    """One recognition model for the whole session; loading it is slow."""
    from app.pipeline.extract_ocr import PaddleOcrEngine

    return PaddleOcrEngine()


@pytest.fixture(scope="session")
def api_client() -> Iterator["TestClient"]:  # noqa: F821
    """A TestClient over the real app, backed by the temporary SQLite database."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.models.db import init_db, reset_engine

    reset_engine()
    init_db()
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def synchronous_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run conversions inline instead of handing them to Celery."""
    import app.worker as worker_module
    from app.services import run_conversion

    class _Inline:
        @staticmethod
        def delay(job_id: str) -> None:
            run_conversion(job_id)

    monkeypatch.setattr(worker_module, "convert_job", _Inline)


@pytest.fixture()
def job_dir(tmp_path: Path) -> Iterator[Path]:
    """An isolated per-test job directory, mirroring ``data/{job_id}/``."""
    path = tmp_path / "job"
    path.mkdir(parents=True, exist_ok=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:  # noqa: ANN001
    """Print the accuracy table after the run, as the verification protocol requires."""
    for phase, reports in sorted(_REPORTS.items()):
        terminalreporter.write_line(format_summary(reports, f"{phase} - cell accuracy"))

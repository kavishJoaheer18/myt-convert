"""Shared test wiring: a job workspace per test and the end-of-run summary."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterator

import pytest

from tests.accuracy import AccuracyReport, format_summary

#: Reports collected by every phase's tests, printed once the session ends.
_REPORTS: dict[str, list[AccuracyReport]] = {}


def record_report(phase: str, report: AccuracyReport) -> None:
    _REPORTS.setdefault(phase, []).append(report)


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

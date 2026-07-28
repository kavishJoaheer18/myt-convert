"""Render a produced workbook back to PDF with LibreOffice.

This closes the loop.  A workbook that openpyxl writes without complaint can
still be rejected by a real spreadsheet application — an out-of-range column
width, an overlapping merge, a malformed number format — and the only way to
know is to hand it to one.  Phase 4 also needs the render as an image to diff
against the source page.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

#: Where LibreOffice lives on the platforms this runs on.
_CANDIDATE_BINARIES = (
    "soffice",
    "libreoffice",
    "/usr/bin/soffice",
    "/usr/lib/libreoffice/program/soffice",
    "C:/Program Files/LibreOffice/program/soffice.exe",
    "C:/Program Files (x86)/LibreOffice/program/soffice.exe",
)

DEFAULT_TIMEOUT_S = 180


class LibreOfficeNotFound(RuntimeError):
    """LibreOffice is not installed or not on PATH."""


class LibreOfficeRenderError(RuntimeError):
    """LibreOffice ran but did not produce a PDF."""


def find_libreoffice() -> str | None:
    """Locate the LibreOffice binary, or return ``None``."""
    override = os.environ.get("LIBREOFFICE_BIN")
    if override:
        return override if Path(override).exists() or shutil.which(override) else None

    for candidate in _CANDIDATE_BINARIES:
        if Path(candidate).exists():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    return None


def is_available() -> bool:
    return find_libreoffice() is not None


def render_to_pdf(
    xlsx_path: Path, out_dir: Path, timeout_s: int = DEFAULT_TIMEOUT_S
) -> Path:
    """Convert ``xlsx_path`` to PDF and return the produced file.

    Raises :class:`LibreOfficeNotFound` if LibreOffice is missing and
    :class:`LibreOfficeRenderError` if it fails or emits nothing.
    """
    binary = find_libreoffice()
    if binary is None:
        raise LibreOfficeNotFound(
            "LibreOffice not found; set LIBREOFFICE_BIN or install libreoffice-calc"
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    # A private profile keeps concurrent workers from fighting over one config
    # directory, which makes LibreOffice exit silently without converting.
    with tempfile.TemporaryDirectory(prefix="lo_profile_") as profile:
        profile_uri = Path(profile).resolve().as_uri()
        command = [
            binary,
            "--headless",
            "--norestore",
            "--nolockcheck",
            f"-env:UserInstallation={profile_uri}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(xlsx_path),
        ]

        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout_s, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise LibreOfficeRenderError(
                f"LibreOffice timed out after {timeout_s}s on {xlsx_path.name}"
            ) from exc

    produced = out_dir / f"{xlsx_path.stem}.pdf"
    if completed.returncode != 0 or not produced.exists():
        raise LibreOfficeRenderError(
            f"LibreOffice failed on {xlsx_path.name} "
            f"(exit {completed.returncode}): {completed.stderr.strip() or completed.stdout.strip()}"
        )

    logger.info(
        "rendered workbook to pdf",
        extra={"xlsx": str(xlsx_path), "pdf": str(produced), "bytes": produced.stat().st_size},
    )
    return produced

"""Thin, safe wrapper around the pandoc binary."""
from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence

DEFAULT_TIMEOUT_SECONDS = 60

# Same pandoc dialects Jemah Writer uses for export and LaTeX ingest.
MARKDOWN_IN = "markdown+tex_math_dollars+pipe_tables"
MARKDOWN_OUT = (
    "markdown"
    "-header_attributes-bracketed_spans-raw_html-fenced_divs-link_attributes"
    "-simple_tables-multiline_tables-grid_tables"
)


class ConversionError(RuntimeError):
    """Raised when pandoc is missing, times out or fails."""

    def __init__(self, message: str, *, stderr: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr


def pandoc_path() -> str | None:
    configured = (os.environ.get("LATEX2MD_PANDOC") or "").strip()
    if configured:
        return configured
    return shutil.which("pandoc")


def pandoc_available() -> bool:
    return pandoc_path() is not None


def _timeout() -> float:
    raw = (os.environ.get("LATEX2MD_TIMEOUT") or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


def run_pandoc(text: str, *, from_format: str, to_format: str, extra_args: Sequence[str] = ()) -> str:
    """Convert ``text`` with pandoc via stdin/stdout and return the output."""
    binary = pandoc_path()
    if not binary:
        raise ConversionError(
            "pandoc is not installed; install it (https://pandoc.org/installing.html) "
            "or set LATEX2MD_PANDOC to its path"
        )
    # --sandbox stops pandoc reading files named in the document (\\input{/etc/passwd}).
    command = [binary, "--sandbox", f"--from={from_format}", f"--to={to_format}", *extra_args]
    try:
        result = subprocess.run(
            command,
            input=text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=_timeout(),
        )
    except subprocess.TimeoutExpired as exc:
        raise ConversionError(f"pandoc timed out after {exc.timeout:g}s") from exc
    except OSError as exc:
        raise ConversionError(f"could not run pandoc: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "pandoc failed").strip()
        raise ConversionError(f"pandoc failed: {detail}", stderr=result.stderr or "")
    return result.stdout

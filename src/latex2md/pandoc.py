"""Thin, safe wrapper around the pandoc binary."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from typing import NamedTuple

from latex2md.result import ConversionWarning

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


class PandocOutput(NamedTuple):
    stdout: str
    stderr: str


def run_pandoc_output(
    text: str, *, from_format: str, to_format: str, extra_args: Sequence[str] = ()
) -> PandocOutput:
    """Like :func:`run_pandoc`, but also return pandoc's stderr (its warnings)."""
    binary = pandoc_path()
    if not binary:
        raise ConversionError(
            "pandoc is not installed; install it (https://pandoc.org/installing.html) "
            "or set LATEX2MD_PANDOC to its path"
        )
    # --sandbox stops pandoc reading files named in the document (\\input{/etc/passwd}).
    # Files pandoc needs (template, bibliography, CSL) are passed as arguments,
    # which the sandbox allows, after latex2md has checked where they are.
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
    return PandocOutput(result.stdout, result.stderr or "")


def run_pandoc(text: str, *, from_format: str, to_format: str, extra_args: Sequence[str] = ()) -> str:
    """Convert ``text`` with pandoc via stdin/stdout and return the output."""
    return run_pandoc_output(text, from_format=from_format, to_format=to_format, extra_args=extra_args).stdout


# "[INFO] Skipped '\\foo{bar}' at line 3 column 5" (pandoc --verbose).
_SKIPPED_RE = re.compile(r"^Skipped '(.*)' at (?:.* )?line (\d+) column (\d+)\s*$", re.DOTALL)
_COMMAND_NAME_RE = re.compile(r"\\([A-Za-z@]+\*?|.)")
_ENV_NAME_RE = re.compile(r"\\begin\s*\{([^{}]*)\}")
_LINE_RE = re.compile(r"\bline (\d+) column (\d+)")

# Layout and preamble commands pandoc skips that carry no content.
HARMLESS_COMMANDS = frozenset({
    "maketitle", "centering", "raggedright", "raggedleft", "noindent", "indent", "newpage",
    "clearpage", "cleardoublepage", "pagebreak", "nopagebreak", "linebreak", "nolinebreak",
    "vspace", "vspace*", "hspace", "hspace*", "vfill", "hfill", "smallskip", "medskip",
    "bigskip", "par", "linewidth", "textwidth", "columnwidth", "textheight",
    "bibliographystyle", "tableofcontents", "listoffigures", "listoftables", "thispagestyle",
    "pagestyle", "setlength", "addtolength", "setcounter", "addtocounter", "numberwithin",
    "counterwithin", "captionsetup", "graphicspath", "hypersetup", "geometry", "usetikzlibrary",
    "protect", "phantomsection", "addcontentsline", "printbibliography", "FloatBarrier",
    "balance", "IEEEoverridecommandlockouts", "IEEEpeerreviewmaketitle", "sloppy", "fussy",
    "frenchspacing", "normalsize", "small", "footnotesize", "scriptsize", "tiny", "large",
    "Large", "LARGE", "huge", "Huge", "selectfont", "onecolumn", "twocolumn", "flushbottom",
    "raggedbottom", "newline", "relax", "nocite", "looseness", "DeclareGraphicsExtensions",
    "allowdisplaybreaks", "label", "ignorespaces", "leavevmode", "null",
})


def pandoc_messages(stderr: str, *, body_start_line: int = 0) -> list[ConversionWarning]:
    """Turn pandoc's stderr into warnings.

    ``Skipped`` notices (only printed with ``--verbose``) become
    ``unknown_command``/``unknown_environment``; other ``[WARNING]`` lines
    become ``pandoc``. Skips before ``body_start_line`` (the preamble) and
    layout-only commands are ignored: they lose no content.
    """
    messages: list[tuple[str, str]] = []
    for line in stderr.splitlines():
        match = re.match(r"^\[(INFO|WARNING|ERROR)\]\s*(.*)$", line)
        if match:
            messages.append((match.group(1), match.group(2)))
        elif messages and line.strip():
            level, text = messages[-1]
            messages[-1] = (level, f"{text} {line.strip()}")
    warnings: list[ConversionWarning] = []
    for level, text in messages:
        skipped = _SKIPPED_RE.match(text)
        if skipped:
            snippet, line_no, column = skipped.group(1), int(skipped.group(2)), skipped.group(3)
            if line_no < body_start_line or snippet.startswith("\\end"):
                continue
            location = f"line {line_no}, column {column} of the flattened source"
            env = _ENV_NAME_RE.match(snippet)
            if env:
                warnings.append(ConversionWarning("unknown_environment", f"\\begin{{{env.group(1)}}}", location))
                continue
            name = _COMMAND_NAME_RE.match(snippet)
            if name and name.group(1) in HARMLESS_COMMANDS:
                continue
            warnings.append(ConversionWarning("unknown_command", snippet, location))
            continue
        if level in ("WARNING", "ERROR"):
            where = _LINE_RE.search(text)
            location = f"line {where.group(1)}, column {where.group(2)}" if where else None
            warnings.append(ConversionWarning("pandoc", text, location))
    return warnings

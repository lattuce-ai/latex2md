"""The pre-pandoc pipeline as a public step: one self-contained LaTeX file.

Many tools (LLM ingest, diffing, search) want an arXiv project as a single
``.tex`` file rather than Markdown. ``flatten_latex`` does exactly what
:func:`latex2md.latex_to_md` does before calling pandoc, with the same safety
rules: includes are read only from inside ``base_dir``.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from latex2md.comments import strip_comments
from latex2md.includes import expand_includes
from latex2md.mhchem import wrap_text_mode_mhchem
from latex2md.result import ConversionWarning

BIBLIOGRAPHY_RE = re.compile(r"\\bibliography\s*\{[^{}]*\}")


def read_tex(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def sibling_bbl(path: Path) -> str | None:
    """The compiled bibliography arXiv ships next to the main file, if any."""
    bbl_path = path.with_suffix(".bbl")
    return read_tex(bbl_path) if bbl_path.is_file() else None


def flatten_source(
    latex: str,
    *,
    base_dir: str | Path | None,
    bbl: str | None,
    warnings: list[ConversionWarning] | None = None,
) -> str:
    source = expand_includes(strip_comments(latex), base_dir, warnings=warnings)
    if bbl is not None:
        source = BIBLIOGRAPHY_RE.sub(lambda _: strip_comments(bbl), source, count=1)
    return wrap_text_mode_mhchem(source)


def flatten_latex(
    path_or_text: str | os.PathLike[str],
    *,
    base_dir: str | Path | None = None,
    bbl: str | None = None,
) -> str:
    """Return one LaTeX document with comments removed and includes inlined.

    ``path_or_text`` is a file when it is a :class:`pathlib.Path` (or another
    ``os.PathLike``) and LaTeX source when it is a ``str``. For a file,
    ``base_dir`` defaults to its folder and ``bbl`` to a sibling ``.bbl``.
    Without ``base_dir``, include commands in text input are removed.

    Steps: ``%`` comments are stripped, ``\\input``/``\\include``/``\\subfile``/
    ``\\import`` and listing includes are inlined from inside ``base_dir`` only,
    the ``.bbl`` replaces ``\\bibliography{...}``, and text-mode ``\\ce{}`` is
    wrapped in ``$...$`` so it survives as math.
    """
    if isinstance(path_or_text, os.PathLike):
        path = Path(path_or_text)
        return flatten_source(
            read_tex(path),
            base_dir=base_dir or path.parent,
            bbl=bbl if bbl is not None else sibling_bbl(path),
        )
    return flatten_source(path_or_text, base_dir=base_dir, bbl=bbl)

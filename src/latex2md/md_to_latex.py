"""Markdown -> LaTeX."""
from __future__ import annotations

import re

from latex2md.pandoc import MARKDOWN_IN, run_pandoc

MHCHEM_RE = re.compile(r"\\c[ef]\{")
_MHCHEM_PACKAGE = "\\usepackage[version=4]{mhchem}"
_BLANK_RUN_RE = re.compile(r"\n{3,}")
# Older pandoc wraps headings as \hypertarget{id}{%\n\section{...}\label{id}}.
_HYPERTARGET_RE = re.compile(
    r"\\hypertarget\{[^{}]*\}\{%\n(\\(?:sub)*(?:section|paragraph|chapter|part)\*?\{.*\}(?:\\label\{[^{}]*\})?)\}$",
    re.M,
)
_TIGHTLIST_RE = re.compile(r"^\\tightlist\n", re.M)
_CITEP_RE = re.compile(r"\\citep(?=[\[{])")


def _inject_package(latex: str, package_line: str) -> str:
    if package_line in latex:
        return latex
    marker = "\\begin{document}"
    index = latex.find(marker)
    if index == -1:
        return latex
    return f"{latex[:index]}{package_line}\n{latex[index:]}"


def md_to_latex(markdown: str, *, standalone: bool = False) -> str:
    """Convert Markdown to LaTeX.

    By default returns a body fragment; ``standalone=True`` returns a complete
    document (with ``mhchem`` loaded when ``\\ce{}``/``\\cf{}`` is used).
    Citations written as ``[@key]`` become ``\\cite{key}``.
    """
    args = ["--wrap=none", "--natbib", "--no-highlight"]
    if standalone:
        args.append("--standalone")
    latex = run_pandoc(markdown, from_format=MARKDOWN_IN, to_format="latex", extra_args=args)
    latex = _HYPERTARGET_RE.sub(r"\1", latex)
    if standalone:
        if MHCHEM_RE.search(latex):
            latex = _inject_package(latex, _MHCHEM_PACKAGE)
    else:
        # Fragments must not depend on macros defined only in pandoc's template.
        latex = _TIGHTLIST_RE.sub("", latex)
        latex = _CITEP_RE.sub(r"\\cite", latex)
    latex = _BLANK_RUN_RE.sub("\n\n", latex)
    return latex.strip() + "\n"

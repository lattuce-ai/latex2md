"""Markdown -> LaTeX."""
from __future__ import annotations

import re

from latex2md.pandoc import MARKDOWN_IN, pandoc_messages, run_pandoc_output
from latex2md.result import ConversionResult, WarningLog

MHCHEM_RE = re.compile(r"\\c[ef]\{")
_MHCHEM_PACKAGE = "\\usepackage[version=4]{mhchem}"
_BLANK_RUN_RE = re.compile(r"\n{3,}")
# Older pandoc wraps headings as \hypertarget{id}{%\n\section{...}\label{id}}.
_HYPERTARGET_RE = re.compile(
    r"\\hypertarget\{[^{}]*\}\{%\n(\\(?:sub)*(?:section|paragraph|chapter|part)\*?\{.*\}(?:\\label\{[^{}]*\})?)\}$",
    re.MULTILINE,
)
_TIGHTLIST_RE = re.compile(r"^\\tightlist\n", re.MULTILINE)
_CITEP_RE = re.compile(r"\\citep(?=[\[{])")
_PANDOCBOUNDED = "\\pandocbounded{"


def _unwrap_pandocbounded(latex: str) -> str:
    """pandoc >= 3.2 wraps images as \\pandocbounded{\\includegraphics...}.

    The macro is defined only in pandoc's own template, so fragments keep just
    the inner \\includegraphics (whose [keepaspectratio] needs only graphicx).
    """
    out: list[str] = []
    i = 0
    while (start := latex.find(_PANDOCBOUNDED, i)) != -1:
        depth = 1
        j = start + len(_PANDOCBOUNDED)
        while j < len(latex) and depth:
            if latex[j] == "\\":
                j += 2
                continue
            depth += {"{": 1, "}": -1}.get(latex[j], 0)
            j += 1
        if depth:  # unbalanced: leave the rest untouched
            break
        out.append(latex[i:start])
        out.append(latex[start + len(_PANDOCBOUNDED) : j - 1])
        i = j
    out.append(latex[i:])
    return "".join(out)


def _inject_package(latex: str, package_line: str) -> str:
    if package_line in latex:
        return latex
    marker = "\\begin{document}"
    index = latex.find(marker)
    if index == -1:
        return latex
    return f"{latex[:index]}{package_line}\n{latex[index:]}"


def convert_md_to_latex(markdown: str, *, standalone: bool = False) -> ConversionResult:
    """:func:`md_to_latex`, returning a :class:`~latex2md.result.ConversionResult`."""
    warnings = WarningLog()
    args = ["--wrap=none", "--natbib", "--no-highlight"]
    if standalone:
        args.append("--standalone")
    output = run_pandoc_output(markdown, from_format=MARKDOWN_IN, to_format="latex", extra_args=args)
    warnings.extend_unique(pandoc_messages(output.stderr))
    latex = _HYPERTARGET_RE.sub(r"\1", output.stdout)
    if standalone:
        if MHCHEM_RE.search(latex):
            latex = _inject_package(latex, _MHCHEM_PACKAGE)
    else:
        # Fragments must not depend on macros defined only in pandoc's template.
        latex = _TIGHTLIST_RE.sub("", latex)
        latex = _unwrap_pandocbounded(latex)
        latex = _CITEP_RE.sub(r"\\cite", latex)
    latex = _BLANK_RUN_RE.sub("\n\n", latex)
    return ConversionResult(latex.strip() + "\n", list(warnings))


def md_to_latex(markdown: str, *, standalone: bool = False) -> str:
    """Convert Markdown to LaTeX.

    By default returns a body fragment; ``standalone=True`` returns a complete
    document (with ``mhchem`` loaded when ``\\ce{}``/``\\cf{}`` is used).
    Citations written as ``[@key]`` become ``\\cite{key}``.
    """
    return convert_md_to_latex(markdown, standalone=standalone).text

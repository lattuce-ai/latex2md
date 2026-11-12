"""Keep mhchem formulas that appear in text mode.

pandoc only understands ``\\ce{}``/``\\cf{}`` inside math, and silently drops
them in running text ("water is \\ce{H2O}" becomes "water is "). Wrap
text-mode occurrences in ``$...$`` so they survive as inline math.
"""
from __future__ import annotations

import re

_MATH_ENVS = (
    "equation", "align", "alignat", "gather", "multline", "flalign",
    "eqnarray", "math", "displaymath",
)
_MATH_ENV_BEGIN_RE = re.compile(r"\\begin\{(" + "|".join(_MATH_ENVS) + r")\*?\}")
_MHCHEM_RE = re.compile(r"\\c[ef]\s*\{")
_MATH_DELIMITERS = {"$$": "$$", "$": "$", "\\(": "\\)", "\\[": "\\]"}


def _group_end(text: str, open_index: int) -> int | None:
    """Index just past the brace group that opens at ``open_index``."""
    depth = 0
    i = open_index
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def wrap_text_mode_mhchem(latex: str) -> str:
    if not _MHCHEM_RE.search(latex):
        return latex
    out: list[str] = []
    i = 0
    closing: str | None = None  # delimiter that ends the current math span
    while i < len(latex):
        if closing is not None:
            if latex.startswith(closing, i):
                out.append(closing)
                i += len(closing)
                closing = None
            elif latex[i] == "\\":
                out.append(latex[i : i + 2])
                i += 2
            else:
                out.append(latex[i])
                i += 1
            continue
        env = _MATH_ENV_BEGIN_RE.match(latex, i)
        if env:
            closing = "\\end{" + env.group(0)[len("\\begin{") :]
            out.append(env.group(0))
            i = env.end()
            continue
        chem = _MHCHEM_RE.match(latex, i)
        if chem:
            end = _group_end(latex, chem.end() - 1)
            if end is not None:
                out.append("$" + latex[i:end] + "$")
                i = end
                continue
        opened = next((d for d in _MATH_DELIMITERS if latex.startswith(d, i)), None)
        if opened:
            out.append(opened)
            i += len(opened)
            closing = _MATH_DELIMITERS[opened]
            continue
        if latex[i] == "\\":
            out.append(latex[i : i + 2])
            i += 2
            continue
        out.append(latex[i])
        i += 1
    return "".join(out)

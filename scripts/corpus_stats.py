"""Structural measurements of converted Markdown, shared by the corpus tools.

Used by ``scripts/fetch_corpus.py --add`` to propose expectations and by
``tests/test_corpus.py`` to check them.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

_FENCE_RE = re.compile(r"^(`{3,}|~{3,}).*?^\1[ \t]*$", re.MULTILINE | re.DOTALL)
_FRONT_MATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_DISPLAY_MATH_RE = re.compile(r"\$\$.+?\$\$", re.DOTALL)
# Inline math may span lines ($\begin{pmatrix} ... \end{pmatrix}$).
_INLINE_MATH_RE = re.compile(r"(?<![\\$])\$(?!\$)(?:\\.|[^$\\])+\$")
_INLINE_CODE_RE = re.compile(r"(`+).+?\1", re.DOTALL)
_HEADING_RE = re.compile(r"^#{1,6} \S", re.MULTILINE)
_TABLE_RULE_RE = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$", re.MULTILINE)
_REFERENCES_RE = re.compile(r"^# (?:References|Bibliography)\s*\n(.*?)(?=^# |\Z)", re.MULTILINE | re.DOTALL)
LEAKS = ("\\begin{", "\\end{", "<div", ":::")


@dataclass(frozen=True)
class Stats:
    headings: int
    display_equations: int
    tables: int
    references: int
    leaks: tuple[str, ...]

    def as_dict(self) -> dict:
        return asdict(self)


def prose(markdown: str) -> str:
    """The Markdown without front matter, code and math."""
    text = _FRONT_MATTER_RE.sub("", markdown)
    text = _FENCE_RE.sub("", text)
    text = _DISPLAY_MATH_RE.sub("", text)
    text = _INLINE_CODE_RE.sub("", text)
    return _INLINE_MATH_RE.sub("", text)


def measure(markdown: str) -> Stats:
    body = _FENCE_RE.sub("", _FRONT_MATTER_RE.sub("", markdown))
    references = sum(
        len(re.findall(r"^[-*] \S", block, re.MULTILINE)) for block in _REFERENCES_RE.findall(body)
    )
    text = prose(markdown)
    return Stats(
        headings=len(_HEADING_RE.findall(body)),
        display_equations=len(_DISPLAY_MATH_RE.findall(body)),
        tables=len(_TABLE_RULE_RE.findall(body)),
        references=references,
        leaks=tuple(leak for leak in LEAKS if leak in text),
    )


def expectations(stats: list[Stats]) -> dict:
    """Ranges with some slack around measurements (e.g. one per pandoc version)."""
    low = min(s.headings for s in stats)
    high = max(s.headings for s in stats)
    return {
        "headings": [max(1, int(low * 0.8)), int(high * 1.2) + 1],
        "min_display_equations": int(min(s.display_equations for s in stats) * 0.8),
        "min_tables": int(min(s.tables for s in stats) * 0.8),
        "min_references": int(min(s.references for s in stats) * 0.8),
    }

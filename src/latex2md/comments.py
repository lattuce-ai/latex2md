"""LaTeX comment stripping that leaves verbatim content alone."""
from __future__ import annotations

import re

# A % starts a comment unless it is escaped (\%).
_COMMENT_RE = re.compile(r"(?<!\\)%.*$", re.M)
_COMMENT_ONLY_LINE_RE = re.compile(r"^[ \t]*(?<!\\)%.*\n", re.M)
_VERBATIM_RE = re.compile(r"\\begin\{(verbatim\*?|lstlisting|minted|comment)\}.*?\\end\{\1\}", re.S)
_VERB_INLINE_RE = re.compile(r"\\verb\*?([^a-zA-Z\s*]).*?\1")


def strip_comments(latex: str) -> str:
    """Remove % comments, leaving verbatim environments and \\verb untouched."""
    protected: list[str] = []

    def protect(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"\x00{len(protected) - 1}\x00"

    text = _VERBATIM_RE.sub(protect, latex)
    text = _VERB_INLINE_RE.sub(protect, text)
    text = _COMMENT_ONLY_LINE_RE.sub("", text)
    text = _COMMENT_RE.sub("", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: protected[int(m.group(1))], text)

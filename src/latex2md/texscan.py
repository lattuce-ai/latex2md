"""Small helpers for reading LaTeX arguments and environments by hand.

pandoc parses LaTeX well but throws away what latex2md needs for numbering
(``align`` vs ``align*``, ``\\nonumber``, which caption belongs to which
float). The pre-pandoc passes therefore look at the source themselves; these
helpers keep that brace- and environment-aware without a full TeX parser.
"""
from __future__ import annotations

import re

VERBATIM_ENVS = frozenset({"verbatim", "verbatim*", "Verbatim", "lstlisting", "minted", "comment", "BVerbatim"})
_VERBATIM_RE = re.compile(
    r"\\begin\{(" + "|".join(re.escape(e) for e in sorted(VERBATIM_ENVS)) + r")\}.*?\\end\{\1\}", re.DOTALL
)
_VERB_RE = re.compile(r"\\verb\*?([^a-zA-Z\s*]).*?\1")


def skip_space(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    return i


def group_end(text: str, i: int) -> int | None:
    """Index just past the brace group opening at ``text[i] == "{"``."""
    depth = 0
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


def read_group(text: str, i: int) -> tuple[str, int] | None:
    """Read ``{...}`` (after optional spaces) at ``i``: (content, end)."""
    j = skip_space(text, i)
    if j < len(text) and text[j] == "{":
        end = group_end(text, j)
        if end is not None:
            return text[j + 1 : end - 1], end
    return None


def read_optional(text: str, i: int) -> tuple[str, int] | None:
    """Read ``[...]`` (after optional spaces) at ``i``, ignoring ``]`` inside braces."""
    j = skip_space(text, i)
    if j >= len(text) or text[j] != "[":
        return None
    depth = 0
    k = j + 1
    while k < len(text):
        char = text[k]
        if char == "\\":
            k += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == "]" and depth <= 0:
            return text[j + 1 : k], k + 1
        k += 1
    return None


def find_env_end(text: str, name: str, start: int) -> tuple[int, int] | None:
    """Locate the ``\\end{name}`` matching a ``\\begin{name}`` that ends at ``start``.

    Returns (index of ``\\end``, index just past it).
    """
    pattern = re.compile(r"\\(begin|end)\s*\{" + re.escape(name) + r"\}")
    depth = 1
    for match in pattern.finditer(text, start):
        depth += 1 if match.group(1) == "begin" else -1
        if depth == 0:
            return match.start(), match.end()
    return None


def split_top_level(text: str, separator: str = "\\\\") -> list[tuple[str, str]]:
    """Split ``text`` at ``separator`` outside braces and nested environments.

    Returns ``(chunk, separator_text)`` pairs; the last separator is empty. A
    row separator keeps its ``*`` and ``[2pt]`` suffix so rows rebuild exactly.
    """
    parts: list[tuple[str, str]] = []
    depth = 0
    env_depth = 0
    start = 0
    i = 0
    while i < len(text):
        if text.startswith("\\begin", i) and not text[i + 6 : i + 7].isalpha():
            env_depth += 1
            i += 6
            continue
        if text.startswith("\\end", i) and not text[i + 4 : i + 5].isalpha():
            env_depth -= 1
            i += 4
            continue
        if depth == 0 and env_depth == 0 and text.startswith(separator, i):
            j = i + len(separator)
            if j < len(text) and text[j] == "*":
                j += 1
            if separator == "\\\\" and text[j : j + 1] == "[" and (optional := read_optional(text, j)):
                j = optional[1]
            parts.append((text[start:i], text[i:j]))
            start = i = j
            continue
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        i += 1
    parts.append((text[start:], ""))
    return parts


def protect_verbatim(text: str) -> tuple[str, list[str]]:
    """Replace verbatim environments and ``\\verb`` with placeholders."""
    saved: list[str] = []

    def save(match: re.Match[str]) -> str:
        saved.append(match.group(0))
        return f"\x00V{len(saved) - 1}\x00"

    return _VERB_RE.sub(save, _VERBATIM_RE.sub(save, text)), saved


def restore_verbatim(text: str, saved: list[str]) -> str:
    return re.sub(r"\x00V(\d+)\x00", lambda m: saved[int(m.group(1))], text)


_SPECIAL = {
    "\\": "\\textbackslash{}",
    "{": "\\{",
    "}": "\\}",
    "#": "\\#",
    "$": "\\$",
    "%": "\\%",
    "&": "\\&",
    "_": "\\_",
    "~": "\\textasciitilde{}",
    "^": "\\textasciicircum{}",
}


def escape_text(text: str) -> str:
    """Escape plain text so it can be put back into LaTeX source."""
    return "".join(_SPECIAL.get(char, char) for char in text)

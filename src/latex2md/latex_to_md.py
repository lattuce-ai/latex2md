"""LaTeX -> Markdown."""
from __future__ import annotations

import re
from importlib import resources

from latex2md.pandoc import MARKDOWN_OUT, run_pandoc

# A % starts a comment unless it is escaped (\%).
_COMMENT_RE = re.compile(r"(?<!\\)%.*$", re.M)
_COMMENT_ONLY_LINE_RE = re.compile(r"^[ \t]*%.*\n", re.M)
_VERBATIM_RE = re.compile(r"\\begin\{(verbatim\*?|lstlisting|minted)\}.*?\\end\{\1\}", re.S)
_VERB_INLINE_RE = re.compile(r"\\verb\*?(.).*?\1")

# Leftover pandoc attribute blocks such as {#sec:intro} or {.unnumbered}.
_ATTR_RE = re.compile(r"[ \t]*\{(?:[#.][\w:.-]+[ \t]*|[\w-]+=\"[^\"]*\"[ \t]*)+\}")
_CODE_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
_BLANK_RUN_RE = re.compile(r"\n{3,}")
# pandoc pads list markers to a tab stop ("-   item", "1.  item").
_LIST_MARKER_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])[ ]{2,}(?=\S)")
_LUA_FILTER = "latex_to_md.lua"
_FENCE_CLASS_RE = re.compile(r"^(\s*)(`{3,}|~{3,}) (\w[\w-]*)$")
_EMPTY_TABLE_ROW_RE = re.compile(r"^\|(?:\s*\|)+$")
_TABLE_RULE_RE = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+$")


def _promote_headerless_tables(lines: list[str]) -> list[str]:
    """LaTeX tabulars have no header row; pandoc then writes an empty one.

    Use the first body row as the header instead, which is what authors mean
    in almost every case and reads far better.
    """
    out: list[str] = []
    i = 0
    while i < len(lines):
        if (
            i + 2 < len(lines)
            and _EMPTY_TABLE_ROW_RE.match(lines[i])
            and _TABLE_RULE_RE.match(lines[i + 1])
            and lines[i + 2].startswith("|")
        ):
            out.extend([lines[i + 2], lines[i + 1]])
            i += 3
            continue
        out.append(lines[i])
        i += 1
    return out


def _strip_comments(latex: str) -> str:
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


def _clean_markdown(markdown: str) -> str:
    lines: list[str] = []
    in_code = False
    for line in markdown.splitlines():
        if _CODE_FENCE_RE.match(line.lstrip()):
            in_code = not in_code
            lines.append(_FENCE_CLASS_RE.sub(r"\1\2\3", line))
            continue
        if not in_code:
            line = _ATTR_RE.sub("", line).rstrip()
            line = _LIST_MARKER_RE.sub(r"\1\2 ", line)
        lines.append(line)
    text = "\n".join(_promote_headerless_tables(lines))
    return _BLANK_RUN_RE.sub("\n\n", text).strip() + "\n"


def latex_to_md(latex: str) -> str:
    """Convert LaTeX (a full document or a fragment) to Markdown.

    Math is kept as ``$...$`` / ``$$...$$``, ``\\cite{key}`` becomes ``[@key]``,
    and pandoc-only attribute/div syntax is removed so the output is plain Markdown.
    """
    with resources.as_file(resources.files("latex2md") / _LUA_FILTER) as lua_filter:
        markdown = run_pandoc(
            _strip_comments(latex),
            from_format="latex",
            to_format=MARKDOWN_OUT,
            extra_args=["--wrap=none", f"--lua-filter={lua_filter}"],
        )
    return _clean_markdown(markdown)

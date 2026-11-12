"""LaTeX -> Markdown."""
from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

from latex2md.comments import strip_comments
from latex2md.includes import expand_includes
from latex2md.mhchem import wrap_text_mode_mhchem
from latex2md.pandoc import MARKDOWN_OUT, pandoc_messages, run_pandoc_output
from latex2md.result import ConversionResult, WarningLog

# Leftover pandoc attribute blocks such as {#sec:intro} or {.unnumbered}.
_ATTR_RE = re.compile(r"[ \t]*\{(?:[#.][\w:.-]+[ \t]*|[\w-]+=\"[^\"]*\"[ \t]*)+\}")
_CODE_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
_BLANK_RUN_RE = re.compile(r"\n{3,}")
# pandoc pads list markers to a tab stop ("-   item", "1.  item").
_LIST_MARKER_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])[ ]{2,}(?=\S)")
_LUA_FILTER = "latex_to_md.lua"
# thebibliography's {widest-label} argument and \bibitem keys otherwise leak
# into the text; turn the environment into a plain list under a heading.
_THEBIBLIOGRAPHY_BEGIN_RE = re.compile(r"\\begin\{thebibliography\}\s*\{[^{}]*\}")
_THEBIBLIOGRAPHY_END_RE = re.compile(r"\\end\{thebibliography\}")
_BIBITEM_RE = re.compile(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}")
_BIBLIOGRAPHY_RE = re.compile(r"\\bibliography\s*\{[^{}]*\}")
_BIB_COMMAND_RE = re.compile(r"\\(?:bibliography|addbibresource)\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}")
_BEGIN_DOCUMENT = "\\begin{document}"
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


def _bibliography_as_list(latex: str) -> str:
    latex = _THEBIBLIOGRAPHY_BEGIN_RE.sub(lambda _: "\\section*{References}\n\\begin{itemize}", latex)
    latex = _THEBIBLIOGRAPHY_END_RE.sub(lambda _: "\\end{itemize}", latex)
    return _BIBITEM_RE.sub(lambda _: "\\item ", latex)


def _body_start_line(source: str) -> int:
    index = source.find(_BEGIN_DOCUMENT)
    return source.count("\n", 0, index) + 1 if index != -1 else 0


def convert_latex_to_md(
    latex: str,
    *,
    base_dir: str | Path | None = None,
    front_matter: bool = True,
    bbl: str | None = None,
) -> ConversionResult:
    """Convert LaTeX to Markdown and report what could not be carried over.

    Takes the same arguments as :func:`latex_to_md` and returns a
    :class:`~latex2md.result.ConversionResult` whose ``warnings`` list skipped
    includes, commands and environments pandoc did not know, and missing
    bibliographies.
    """
    warnings = WarningLog()
    source = expand_includes(strip_comments(latex), base_dir, warnings=warnings)
    if bbl is not None:
        source = _BIBLIOGRAPHY_RE.sub(lambda _: strip_comments(bbl), source, count=1)
    else:
        for match in _BIB_COMMAND_RE.finditer(source):
            warnings.add(
                "missing_bibliography",
                f"{match.group(0)}: no .bbl given, so citations stay as [@key]",
            )
    source = wrap_text_mode_mhchem(_bibliography_as_list(source))
    args = ["--wrap=none", "--verbose"]
    args.append("--standalone" if front_matter else "--metadata=latex2md_body_abstract:true")
    with resources.as_file(resources.files("latex2md") / _LUA_FILTER) as lua_filter:
        output = run_pandoc_output(
            source,
            from_format="latex",
            to_format=MARKDOWN_OUT,
            extra_args=[*args, f"--lua-filter={lua_filter}"],
        )
    warnings.extend_unique(pandoc_messages(output.stderr, body_start_line=_body_start_line(source)))
    return ConversionResult(_clean_markdown(output.stdout), list(warnings))


def latex_to_md(
    latex: str,
    *,
    base_dir: str | Path | None = None,
    front_matter: bool = True,
    bbl: str | None = None,
) -> str:
    """Convert LaTeX (a full document or a fragment) to Markdown.

    Math is kept as ``$...$`` / ``$$...$$``, ``\\cite{key}`` becomes ``[@key]``,
    and pandoc-only attribute/div syntax is removed so the output is plain Markdown.

    ``\\input``/``\\include``/``\\subfile``/``\\import`` and listing includes are
    inlined from ``base_dir`` (the project folder); files outside it are never
    read. Without ``base_dir`` include commands are dropped.

    ``front_matter=True`` writes title/author/date/abstract as YAML front matter;
    ``False`` drops title/author and puts the abstract under an "Abstract"
    heading. ``bbl`` (compiled bibliography) replaces ``\\bibliography{...}``.

    Use :func:`convert_latex_to_md` to also get the conversion warnings.
    """
    return convert_latex_to_md(latex, base_dir=base_dir, front_matter=front_matter, bbl=bbl).text


def convert_latex_file_to_md(
    path: str | Path,
    *,
    base_dir: str | Path | None = None,
    front_matter: bool = True,
) -> ConversionResult:
    """:func:`latex_file_to_md`, returning a :class:`~latex2md.result.ConversionResult`."""
    path = Path(path)
    bbl_path = path.with_suffix(".bbl")
    bbl = bbl_path.read_text(encoding="utf-8", errors="replace") if bbl_path.is_file() else None
    return convert_latex_to_md(
        path.read_text(encoding="utf-8", errors="replace"),
        base_dir=base_dir or path.parent,
        front_matter=front_matter,
        bbl=bbl,
    )


def latex_file_to_md(
    path: str | Path,
    *,
    base_dir: str | Path | None = None,
    front_matter: bool = True,
) -> str:
    """Convert a ``.tex`` file.

    Includes resolve under its folder (or ``base_dir``), and a sibling ``.bbl``
    with the same name, as shipped in arXiv sources, fills in the bibliography.
    """
    return convert_latex_file_to_md(path, base_dir=base_dir, front_matter=front_matter).text

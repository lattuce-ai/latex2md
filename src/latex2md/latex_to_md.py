"""LaTeX -> Markdown."""
from __future__ import annotations

import re
import tempfile
from importlib import resources
from pathlib import Path
from typing import Literal

from latex2md.archive import ArchiveLimits, extract_archive
from latex2md.bibliography import (
    BIB_COMMAND_RE,
    PRINT_BIBLIOGRAPHY_RE,
    BibCopies,
    BibFiles,
    checked_file,
    find_bib_files,
)
from latex2md.flatten import flatten_source, read_tex, sibling_bbl
from latex2md.pandoc import (
    MARKDOWN_OUT,
    PandocOutput,
    pandoc_messages,
    run_pandoc_output,
)
from latex2md.result import ConversionResult, WarningLog
from latex2md.structure import resolve_structure

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
_BEGIN_DOCUMENT = "\\begin{document}"
# LyX and older preambles write \global\long\def; pandoc then silently returns
# an empty document. The prefixes do not matter for conversion.
_DEF_PREFIX_RE = re.compile(r"(?:\\(?:global|long|outer|protected)(?![A-Za-z])\s*)+(?=\\[gex]?def(?![A-Za-z]))")
# Where citeproc's reference list goes; the Lua filter swaps it in.
_REFERENCES_PLACEHOLDER = "\\par LATEX2MDREFERENCES\\par "
CiteStyle = Literal["keep", "rendered"]
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


def _place_references(source: str) -> str:
    """Mark where the reference list goes and drop the bibliography commands.

    pandoc would otherwise put the list at the very end and try to read the
    named ``.bib`` itself; latex2md passes the checked file instead.
    """
    marker = PRINT_BIBLIOGRAPHY_RE if PRINT_BIBLIOGRAPHY_RE.search(source) else re.compile(r"\\bibliography\s*\{[^{}]*\}")
    begin = source.find(_BEGIN_DOCUMENT)
    match = marker.search(source, max(begin, 0))
    if match:
        source = source[: match.start()] + _REFERENCES_PLACEHOLDER + source[match.end() :]
    return PRINT_BIBLIOGRAPHY_RE.sub("", BIB_COMMAND_RE.sub("", source))


def convert_latex_to_md(
    latex: str,
    *,
    base_dir: str | Path | None = None,
    front_matter: bool = True,
    bbl: str | None = None,
    anchors: bool = False,
    csl: str | Path | None = None,
    cite_style: CiteStyle = "keep",
) -> ConversionResult:
    """Convert LaTeX to Markdown and report what could not be carried over.

    Takes the same arguments as :func:`latex_to_md` and returns a
    :class:`~latex2md.result.ConversionResult` whose ``warnings`` list skipped
    includes, commands and environments pandoc did not know, unresolved
    references and missing or malformed bibliographies.
    """
    if cite_style not in ("keep", "rendered"):
        raise ValueError(f"cite_style must be 'keep' or 'rendered', not {cite_style!r}")
    warnings = WarningLog()
    source = _DEF_PREFIX_RE.sub("", flatten_source(latex, base_dir=base_dir, bbl=bbl, warnings=warnings))
    bibs = BibFiles() if bbl is not None else find_bib_files(source, base_dir)
    warnings.extend_unique(bibs.warnings)
    style = checked_file(csl, base_dir, what="CSL style") if csl is not None else None
    source, structure_warnings = resolve_structure(_bibliography_as_list(source), anchors=anchors)
    warnings.extend_unique(structure_warnings)
    args = ["--wrap=none", "--verbose"]
    args.append("--standalone" if front_matter else "--metadata=latex2md_body_abstract:true")
    if anchors:
        args.append("--metadata=latex2md_anchors:true")
    with (
        tempfile.TemporaryDirectory(prefix="latex2md-bib-") as folder,
        resources.as_file(resources.files("latex2md") / _LUA_FILTER) as lua_filter,
    ):
        cite_args: list[str] = []
        cited_source = source
        copies = BibCopies(bibs.paths, Path(folder), warnings)
        if bibs.paths:
            cite_args = ["--citeproc", "--metadata=latex2md_citeproc:true"]
            if style is not None:
                cite_args.append(f"--csl={style}")
            if cite_style == "rendered":
                cite_args.append("--metadata=latex2md_cite_rendered:true")
            cited_source = _place_references(source)

        def run(text: str, extra: list[str]) -> PandocOutput:
            return run_pandoc_output(
                text,
                from_format="latex",
                to_format=MARKDOWN_OUT,
                extra_args=[*args, *extra, f"--lua-filter={lua_filter}"],
            )

        output = copies.run(lambda bib_args: run(cited_source, [*cite_args, *bib_args])) if cite_args else None
        if output is None:
            if cite_args:
                warnings.add("bibliography", "pandoc could not read the bibliography; citations stay as [@key]")
            cited_source = source
            output = run(source, [])
    warnings.extend_unique(pandoc_messages(output.stderr, body_start_line=_body_start_line(cited_source)))
    return ConversionResult(_clean_markdown(output.stdout), list(warnings))


def latex_to_md(
    latex: str,
    *,
    base_dir: str | Path | None = None,
    front_matter: bool = True,
    bbl: str | None = None,
    anchors: bool = False,
    csl: str | Path | None = None,
    cite_style: CiteStyle = "keep",
) -> str:
    """Convert LaTeX (a full document or a fragment) to Markdown.

    Math is kept as ``$...$`` / ``$$...$$``, ``\\cite{key}`` becomes ``[@key]``,
    and pandoc-only attribute/div syntax is removed so the output is plain Markdown.

    ``\\input``/``\\include``/``\\subfile``/``\\import`` and listing includes are
    inlined from ``base_dir`` (the project folder); files outside it are never
    read. Without ``base_dir`` include commands are dropped.

    ``front_matter=True`` writes title/author/date/abstract as YAML front matter;
    ``False`` drops title/author and puts the abstract under an "Abstract"
    heading.

    Bibliography: ``bbl`` (compiled bibliography) replaces ``\\bibliography{...}``.
    Without it, a ``.bib`` named by ``\\bibliography``/``\\addbibresource`` inside
    ``base_dir`` is rendered by pandoc's citeproc as a "References" section,
    in pandoc's default style or the CSL file ``csl`` (which must be inside
    ``base_dir`` when one is given). ``cite_style="keep"`` leaves ``[@key]`` in
    the text; ``"rendered"`` writes citeproc's in-text citations instead.

    Display equations, sections, figures, tables, theorems and algorithms are
    numbered as LaTeX would number them; ``\\ref``/``\\eqref``/``\\cref`` become
    those numbers. ``anchors=True`` turns references to sections into links
    to the heading's GitHub-style id, e.g. ``[3](#method)``.

    Use :func:`convert_latex_to_md` to also get the conversion warnings.
    """
    return convert_latex_to_md(
        latex,
        base_dir=base_dir,
        front_matter=front_matter,
        bbl=bbl,
        anchors=anchors,
        csl=csl,
        cite_style=cite_style,
    ).text


def convert_latex_file_to_md(
    path: str | Path,
    *,
    base_dir: str | Path | None = None,
    front_matter: bool = True,
    anchors: bool = False,
    csl: str | Path | None = None,
    cite_style: CiteStyle = "keep",
) -> ConversionResult:
    """:func:`latex_file_to_md`, returning a :class:`~latex2md.result.ConversionResult`."""
    path = Path(path)
    return convert_latex_to_md(
        read_tex(path),
        base_dir=base_dir or path.parent,
        front_matter=front_matter,
        bbl=sibling_bbl(path),
        anchors=anchors,
        csl=csl,
        cite_style=cite_style,
    )


def latex_file_to_md(
    path: str | Path,
    *,
    base_dir: str | Path | None = None,
    front_matter: bool = True,
    anchors: bool = False,
    csl: str | Path | None = None,
    cite_style: CiteStyle = "keep",
) -> str:
    """Convert a ``.tex`` file.

    Includes resolve under its folder (or ``base_dir``). A sibling ``.bbl``
    with the same name, as shipped in arXiv sources, fills in the
    bibliography; otherwise a ``.bib`` inside the folder is used (see
    :func:`latex_to_md`).
    """
    return convert_latex_file_to_md(
        path, base_dir=base_dir, front_matter=front_matter, anchors=anchors, csl=csl, cite_style=cite_style
    ).text


def convert_latex_archive_to_md(
    data: bytes,
    *,
    front_matter: bool = True,
    limits: ArchiveLimits | None = None,
    anchors: bool = False,
    cite_style: CiteStyle = "keep",
) -> ConversionResult:
    """:func:`latex_archive_to_md`, returning a :class:`~latex2md.result.ConversionResult`.

    Archive members that were not extracted are reported as ``skipped_member``.
    """
    with extract_archive(data, limits=limits) as archive:
        result = convert_latex_file_to_md(
            archive.main_tex, base_dir=archive.root, front_matter=front_matter, anchors=anchors, cite_style=cite_style
        )
    warnings = WarningLog(result.warnings)
    for message in archive.skipped:
        warnings.add("skipped_member", message)
    return ConversionResult(result.text, list(warnings))


def latex_archive_to_md(
    data: bytes,
    *,
    front_matter: bool = True,
    limits: ArchiveLimits | None = None,
    anchors: bool = False,
    cite_style: CiteStyle = "keep",
) -> str:
    """Convert an arXiv-style source archive (zip, tar, tar.gz, gzip'd or bare ``.tex``).

    The archive is unpacked into a private temporary folder under ``limits``
    (see :class:`~latex2md.archive.ArchiveLimits`), the main file is picked as
    LaTeX would be run on it, and it is converted like :func:`latex_file_to_md`
    (a ``.bbl`` or, failing that, a ``.bib`` in the archive gives the references).
    """
    return convert_latex_archive_to_md(
        data, front_matter=front_matter, limits=limits, anchors=anchors, cite_style=cite_style
    ).text

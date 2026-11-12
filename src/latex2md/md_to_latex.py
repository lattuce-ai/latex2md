"""Markdown -> LaTeX."""
from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from latex2md.bibliography import MAX_BIB_BYTES, BibCopies, checked_file
from latex2md.images import filter_images, references_as_list
from latex2md.pandoc import (
    MARKDOWN_IN,
    ConversionError,
    PandocOutput,
    pandoc_messages,
    run_pandoc_output,
)
from latex2md.result import ConversionResult, WarningLog

Citations = Literal["cite", "natbib", "biblatex", "citeproc"]
_VARIABLE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_MAX_TEMPLATE_BYTES = 1024 * 1024
# pandoc --verbose: [INFO] Not rendering Image ("",[],[]) [Str "alt"] ("data:...","")
_NOT_RENDERED_RE = re.compile(r'^\[INFO\] Not rendering Image .*\("((?:[^"\\]|\\.)*)","(?:[^"\\]|\\.)*"\)\s*$', re.MULTILINE)

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


def _citation_args(citations: str, bibliography: str | Path | None, style: Path | None) -> tuple[list[str], list[str]]:
    """pandoc arguments for (Markdown -> JSON, JSON -> LaTeX); bibliography files come from BibCopies."""
    if citations == "citeproc":
        return ["--citeproc", *([f"--csl={style}"] if style is not None else [])], []
    writer = ["--biblatex" if citations == "biblatex" else "--natbib"]
    if bibliography is not None:
        # Only named in a standalone document's preamble; the path is the caller's
        # own. BibTeX's \bibliography{} takes the name without ".bib".
        name = str(bibliography)
        if citations != "biblatex" and name.lower().endswith(".bib"):
            name = name[:-4]
        writer.append(f"--metadata=bibliography:{name}")
    return [], writer


def convert_md_to_latex(
    markdown: str,
    *,
    standalone: bool = False,
    template: str | Path | None = None,
    variables: Mapping[str, str] | None = None,
    bibliography: str | Path | None = None,
    citations: Citations = "cite",
    csl: str | Path | None = None,
    resource_dir: str | Path | None = None,
    allow_remote_images: bool = False,
) -> ConversionResult:
    """:func:`md_to_latex`, returning a :class:`~latex2md.result.ConversionResult`.

    Dropped images are reported as ``dropped_image`` warnings.
    """
    if citations not in ("cite", "natbib", "biblatex", "citeproc"):
        raise ValueError(f"citations must be cite, natbib, biblatex or citeproc, not {citations!r}")
    warnings = WarningLog()
    root = Path(resource_dir).resolve() if resource_dir is not None else None
    if root is not None and not root.is_dir():
        raise ConversionError(f"resource_dir {str(resource_dir)!r} is not a folder")
    template_path = checked_file(template, root, what="template", max_bytes=_MAX_TEMPLATE_BYTES) if template else None
    checked_bib = (
        checked_file(bibliography, root, what="bibliography", max_bytes=MAX_BIB_BYTES) if bibliography else None
    )
    style = checked_file(csl, root, what="CSL style") if csl else None
    standalone = standalone or template_path is not None
    reader_args, writer_args = _citation_args(citations, bibliography, style)

    # Markdown -> JSON (with citeproc), check images in Python, JSON -> LaTeX.
    def parse(extra: list[str]) -> PandocOutput:
        return run_pandoc_output(markdown, from_format=MARKDOWN_IN, to_format="json", extra_args=extra)

    parsed = None
    if citations == "citeproc":
        if checked_bib is None:
            warnings.add("missing_bibliography", "citations='citeproc' without bibliography=; keys stay unresolved")
        with tempfile.TemporaryDirectory(prefix="latex2md-bib-") as folder:
            copies = BibCopies([checked_bib] if checked_bib else [], Path(folder), warnings)
            parsed = copies.run(lambda bib_args: parse([*reader_args, *bib_args]))
        if parsed is None:
            warnings.add("bibliography", "pandoc could not read the bibliography; citations are not rendered")
    if parsed is None:
        parsed = parse([] if citations == "citeproc" else reader_args)
    warnings.extend_unique(pandoc_messages(parsed.stderr))
    ast = json.loads(parsed.stdout)
    warnings.extend_unique(filter_images(ast, resource_dir=root, allow_remote=allow_remote_images))
    if not standalone:
        references_as_list(ast)

    args = ["--wrap=none", "--no-highlight", "--verbose", *writer_args]
    if standalone:
        args.append("--standalone")
    if template_path is not None:
        args.append(f"--template={template_path}")
    for name, value in (variables or {}).items():
        if not _VARIABLE_NAME_RE.match(name):
            raise ValueError(f"invalid template variable name {name!r}")
        args.append(f"--variable={name}:{value}")
    output = run_pandoc_output(json.dumps(ast), from_format="json", to_format="latex", extra_args=args)
    warnings.extend_unique(pandoc_messages(output.stderr))
    for url in _NOT_RENDERED_RE.findall(output.stderr):
        # data: URIs pass latex2md's check, but LaTeX cannot embed them.
        shown = url if len(url) <= 40 else url[:37] + "..."
        warnings.add("dropped_image", f"{shown}: pandoc cannot write this image to LaTeX")
    latex = _HYPERTARGET_RE.sub(r"\1", output.stdout)
    if standalone:
        if MHCHEM_RE.search(latex):
            latex = _inject_package(latex, _MHCHEM_PACKAGE)
    else:
        # Fragments must not depend on macros defined only in pandoc's template.
        latex = _TIGHTLIST_RE.sub("", latex)
        latex = _unwrap_pandocbounded(latex)
        if citations == "cite":
            latex = _CITEP_RE.sub(r"\\cite", latex)
    latex = _BLANK_RUN_RE.sub("\n\n", latex)
    return ConversionResult(latex.strip() + "\n", list(warnings))


def md_to_latex(
    markdown: str,
    *,
    standalone: bool = False,
    template: str | Path | None = None,
    variables: Mapping[str, str] | None = None,
    bibliography: str | Path | None = None,
    citations: Citations = "cite",
    csl: str | Path | None = None,
    resource_dir: str | Path | None = None,
    allow_remote_images: bool = False,
) -> str:
    """Convert Markdown to LaTeX.

    By default returns a body fragment; ``standalone=True`` returns a complete
    document (with ``mhchem`` loaded when ``\\ce{}``/``\\cf{}`` is used).

    ``template`` is a pandoc LaTeX template (implies ``standalone``) and
    ``variables`` sets its ``$variables$``.

    ``citations``: ``"cite"`` (default) writes ``[@key]`` as ``\\cite{key}``;
    ``"natbib"`` keeps ``\\citep``/``\\citet``; ``"biblatex"`` writes
    ``\\autocite``/``\\textcite``; ``"citeproc"`` renders citations and a
    reference list from ``bibliography`` (``.bib`` or CSL JSON) in the ``csl``
    style. With ``natbib``/``biblatex``, a standalone document's preamble
    names ``bibliography``.

    Images: ``data:`` URIs are kept; local paths are kept when they resolve to
    a file inside ``resource_dir`` (without one: when relative and not
    escaping with ``..``); ``http(s)`` only with ``allow_remote_images=True``.
    Others become their alt text (see :func:`convert_md_to_latex` for the
    warnings). ``template``, ``bibliography`` and ``csl`` must be existing
    files, inside ``resource_dir`` when one is given.
    """
    return convert_md_to_latex(
        markdown,
        standalone=standalone,
        template=template,
        variables=variables,
        bibliography=bibliography,
        citations=citations,
        csl=csl,
        resource_dir=resource_dir,
        allow_remote_images=allow_remote_images,
    ).text

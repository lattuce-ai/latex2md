"""Inline \\input / \\include files before pandoc sees the document.

pandoc always runs with ``--sandbox`` (see :mod:`latex2md.pandoc`), so it cannot
read files on its own. This module resolves include commands itself, but only
for files inside ``base_dir``: absolute paths, ``..`` escapes and symlinks that
point outside are dropped. That makes it safe to convert untrusted LaTeX, such
as arXiv source archives.
"""
from __future__ import annotations

import re
from pathlib import Path

from latex2md.comments import strip_comments
from latex2md.result import ConversionWarning

MAX_INCLUDE_DEPTH = 16
MAX_INCLUDED_BYTES = 20 * 1024 * 1024

_GROUP = r"\{\s*([^{}]+?)\s*\}"
# \input{file}, \include{file}, \subfile{file}, \input file
_INPUT_RE = re.compile(r"\\(input|include|subfile)\s*(?:" + _GROUP + r"|\s+([^\s{}\\]+))")
# \import{dir}{file}, \subimport{dir}{file}, starred variants
_IMPORT_RE = re.compile(r"\\(?:sub)?(?:import|inputfrom|includefrom)\*?\s*" + _GROUP + r"\s*" + _GROUP)
# \lstinputlisting[opts]{file}, \verbatiminput{file}
_LISTING_RE = re.compile(r"\\(lstinputlisting|verbatiminput)\s*(?:\[[^\]]*\])?\s*" + _GROUP)


class _Budget:
    def __init__(self) -> None:
        self.remaining = MAX_INCLUDED_BYTES


class _Skip(Exception):
    """An include that is not inlined, with the reason shown in warnings."""


def _resolve(base_dir: Path, current_dir: Path, name: str, *, add_tex: bool) -> Path:
    name = name.strip().strip('"')
    if not name:
        raise _Skip("empty file name")
    if Path(name).is_absolute() or name.startswith("~"):
        raise _Skip("absolute path")
    candidates = [current_dir / name, base_dir / name]
    if add_tex and not name.endswith(".tex"):
        candidates = [path for c in candidates for path in (c.with_name(c.name + ".tex"), c)]
    root = base_dir.resolve()
    outside = False
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError):
            continue
        if not resolved.is_relative_to(root):
            outside = outside or resolved.exists()
            continue
        if resolved.is_file():
            return resolved
    if outside or ".." in Path(name).parts:
        raise _Skip("outside base dir")
    raise _Skip("missing")


def _read(path: Path, budget: _Budget) -> str:
    size = path.stat().st_size
    if size > budget.remaining:
        raise _Skip(f"size budget of {MAX_INCLUDED_BYTES // (1024 * 1024)} MB exceeded")
    budget.remaining -= size
    return path.read_text(encoding="utf-8", errors="replace")


class _Expander:
    def __init__(self, base_dir: Path, warnings: list[ConversionWarning] | None) -> None:
        self.base_dir = base_dir
        self.budget = _Budget()
        self.warnings = warnings

    def skip(self, command: str, reason: str) -> str:
        if self.warnings is not None:
            warning = ConversionWarning("skipped_include", f"{command}: {reason}")
            if warning not in self.warnings:
                self.warnings.append(warning)
        return ""

    def expand(self, text: str, current_dir: Path, stack: tuple[Path, ...]) -> str:
        def include(command: str, name: str) -> str:
            try:
                path = _resolve(self.base_dir, current_dir, name, add_tex=True)
                if path in stack:
                    raise _Skip("include cycle")
                if len(stack) >= MAX_INCLUDE_DEPTH:
                    raise _Skip(f"nested deeper than {MAX_INCLUDE_DEPTH} levels")
                content = _read(path, self.budget)
            except _Skip as skip:
                return self.skip(command, str(skip))
            body = _subfile_body(strip_comments(content))
            return f"\n{self.expand(body, path.parent, (*stack, path))}\n"

        def replace_input(match: re.Match[str]) -> str:
            return include(match.group(0).strip(), match.group(2) or match.group(3) or "")

        def replace_import(match: re.Match[str]) -> str:
            return include(match.group(0).strip(), str(Path(match.group(1)) / match.group(2)))

        def replace_listing(match: re.Match[str]) -> str:
            try:
                path = _resolve(self.base_dir, current_dir, match.group(2), add_tex=False)
                content = _read(path, self.budget)
            except _Skip as skip:
                return self.skip(match.group(0).strip(), str(skip))
            body = content.rstrip("\n").replace("\\end{verbatim}", "")
            return "\n\\begin{verbatim}\n" + body + "\n\\end{verbatim}\n"

        text = _LISTING_RE.sub(replace_listing, text)
        text = _IMPORT_RE.sub(replace_import, text)
        return _INPUT_RE.sub(replace_input, text)


_DOCUMENT_BODY_RE = re.compile(r"\\begin\{document\}(.*)\\end\{document\}", re.DOTALL)


def _subfile_body(text: str) -> str:
    """A \\subfile is a full document; keep only its body."""
    if "\\documentclass" in text:
        match = _DOCUMENT_BODY_RE.search(text)
        if match:
            return match.group(1)
    return text


def expand_includes(latex: str, base_dir: str | Path | None, *, warnings: list[ConversionWarning] | None = None) -> str:
    """Inline include commands resolved under ``base_dir``; drop the rest.

    ``latex`` must already have its comments stripped. With no ``base_dir``
    every include command is removed. Each dropped include is appended to
    ``warnings`` (a list of :class:`~latex2md.result.ConversionWarning`) as a
    ``skipped_include`` with the reason.
    """
    if base_dir is None:
        expander = _Expander(Path.cwd(), warnings)

        def drop(match: re.Match[str]) -> str:
            return expander.skip(match.group(0).strip(), "no base dir given")

        text = _LISTING_RE.sub(drop, latex)
        text = _IMPORT_RE.sub(drop, text)
        return _INPUT_RE.sub(drop, text)
    root = Path(base_dir).resolve()
    return _Expander(root, warnings).expand(latex, root, ())

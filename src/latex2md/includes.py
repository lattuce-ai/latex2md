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


def _resolve(base_dir: Path, current_dir: Path, name: str, *, add_tex: bool) -> Path | None:
    name = name.strip().strip('"')
    if not name or Path(name).is_absolute():
        return None
    candidates = [current_dir / name, base_dir / name]
    if add_tex and not name.endswith(".tex"):
        candidates = [path for c in candidates for path in (c.with_name(c.name + ".tex"), c)]
    root = base_dir.resolve()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_relative_to(root) and resolved.is_file():
            return resolved
    return None


def _read(path: Path, budget: _Budget) -> str | None:
    size = path.stat().st_size
    if size > budget.remaining:
        return None
    budget.remaining -= size
    return path.read_text(encoding="utf-8", errors="replace")


def _expand(text: str, *, base_dir: Path, current_dir: Path, stack: tuple[Path, ...], budget: _Budget) -> str:
    def include(path: Path | None) -> str:
        if path is None or path in stack or len(stack) >= MAX_INCLUDE_DEPTH:
            return ""
        content = _read(path, budget)
        if content is None:
            return ""
        body = _subfile_body(strip_comments(content))
        expanded = _expand(body, base_dir=base_dir, current_dir=path.parent, stack=(*stack, path), budget=budget)
        return f"\n{expanded}\n"

    def replace_input(match: re.Match[str]) -> str:
        name = match.group(2) or match.group(3) or ""
        return include(_resolve(base_dir, current_dir, name, add_tex=True))

    def replace_import(match: re.Match[str]) -> str:
        directory, name = match.group(1), match.group(2)
        return include(_resolve(base_dir, current_dir, str(Path(directory) / name), add_tex=True))

    def replace_listing(match: re.Match[str]) -> str:
        path = _resolve(base_dir, current_dir, match.group(2), add_tex=False)
        content = _read(path, budget) if path else None
        if content is None:
            return ""
        return "\n\\begin{verbatim}\n" + content.rstrip("\n").replace("\\end{verbatim}", "") + "\n\\end{verbatim}\n"

    text = _LISTING_RE.sub(replace_listing, text)
    text = _IMPORT_RE.sub(replace_import, text)
    return _INPUT_RE.sub(replace_input, text)


_DOCUMENT_BODY_RE = re.compile(r"\\begin\{document\}(.*)\\end\{document\}", re.S)


def _subfile_body(text: str) -> str:
    """A \\subfile is a full document; keep only its body."""
    if "\\documentclass" in text:
        match = _DOCUMENT_BODY_RE.search(text)
        if match:
            return match.group(1)
    return text


def expand_includes(latex: str, base_dir: str | Path | None) -> str:
    """Inline include commands resolved under ``base_dir``; drop the rest.

    ``latex`` must already have its comments stripped. With no ``base_dir``
    every include command is removed.
    """
    if base_dir is None:
        text = _LISTING_RE.sub("", latex)
        text = _IMPORT_RE.sub("", text)
        return _INPUT_RE.sub("", text)
    root = Path(base_dir).resolve()
    return _expand(latex, base_dir=root, current_dir=root, stack=(), budget=_Budget())

"""Find, check and sanitise BibTeX files for pandoc's ``--citeproc``.

arXiv sources usually ship a compiled ``.bbl``; when they do not, the ``.bib``
named by ``\\bibliography{refs}`` or ``\\addbibresource{refs.bib}`` is the only
source of the reference list. pandoc reads it itself (files given on the
command line are allowed by ``--sandbox``), so latex2md first checks that it
lies inside the project folder, and drops malformed entries: pandoc's BibTeX
parser rejects the whole file on a single unbalanced brace.

Files a caller names directly (``csl=``, ``template=``, ``bibliography=``) are
checked by :func:`checked_file`.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from latex2md.pandoc import ConversionError
from latex2md.result import ConversionWarning, WarningLog

T = TypeVar("T")
MAX_BIB_RETRIES = 20

MAX_BIB_BYTES = 10 * 1024 * 1024
MAX_BIB_FILES = 16
MAX_STYLE_BYTES = 2 * 1024 * 1024

BIB_COMMAND_RE = re.compile(r"\\(bibliography|addbibresource)\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}")
PRINT_BIBLIOGRAPHY_RE = re.compile(r"\\printbibliography\s*(?:\[[^\]]*\])?")
_ENTRY_START_RE = re.compile(r"^[ \t]*@\s*([A-Za-z]+)\s*([{(])", re.MULTILINE)
_KEY_RE = re.compile(r"\s*[^,\s{}()=\"#%'~\\]+\s*,")


def checked_file(path: str | Path, root: str | Path | None, *, what: str, max_bytes: int = MAX_STYLE_BYTES) -> Path:
    """Resolve a caller-supplied file and refuse anything unsafe.

    It must be an existing regular file of at most ``max_bytes``, and inside
    ``root`` (after resolving symlinks) when a root folder is given.
    """
    candidate = Path(path)
    resolved = candidate.resolve()
    if root is not None and not resolved.is_relative_to(Path(root).resolve()):
        raise ConversionError(f"{what} {str(path)!r} is outside {str(root)!r}")
    if not resolved.is_file():
        raise ConversionError(f"{what} {str(path)!r} is not an existing file")
    if resolved.stat().st_size > max_bytes:
        raise ConversionError(f"{what} {str(path)!r} is larger than {max_bytes} bytes")
    return resolved


def _entry_end(text: str, start: int, opener: str) -> int | None:
    """Index just past the entry body that opens at ``text[start]``."""
    closer = "}" if opener == "{" else ")"
    depth = 0
    for i in range(start, len(text)):
        char = text[i]
        if char == "{" or (char == opener and opener == "("):
            depth += 1
        elif char == "}" or (char == closer and closer == ")"):
            depth -= 1
            if depth == 0:
                return i + 1
            if depth < 0:
                return None
    return None


def sanitize_bib(text: str) -> tuple[str, list[str]]:
    """Keep well-formed entries; describe the ones left out.

    Entries are split at an ``@`` that starts a line, so one broken entry
    cannot swallow the entries after it.
    """
    starts = list(_ENTRY_START_RE.finditer(text))
    kept: list[str] = []
    problems: list[str] = []
    for index, match in enumerate(starts):
        segment_end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        kind = match.group(1).lower()
        head = text[match.start() : min(segment_end, match.start() + 60)].strip().splitlines()[0]
        end = _entry_end(text, match.end() - 1, match.group(2))
        if end is None or end > segment_end:
            problems.append(f"{head}: unbalanced braces")
            continue
        if kind not in ("comment", "preamble", "string") and not _KEY_RE.match(text, match.end()):
            problems.append(f"{head}: no citation key")
            continue
        if kind != "comment":
            kept.append(text[match.start() : end].strip())
    return "\n\n".join(kept) + "\n", problems


@dataclass
class BibFiles:
    """The ``.bib`` files a document names, resolved inside its folder."""

    paths: list[Path] = field(default_factory=list)
    warnings: list[ConversionWarning] = field(default_factory=list)
    commands: bool = False  # the document asks for a bibliography at all


def find_bib_files(source: str, base_dir: str | Path | None, *, start_dir: str | Path | None = None) -> BibFiles:
    """BibTeX looks next to the main file (``start_dir``); fall back to the root."""
    found = BibFiles()
    root = Path(base_dir).resolve() if base_dir is not None else None
    start = Path(start_dir).resolve() if start_dir is not None and root is not None else root
    if start is not None and root is not None and not start.is_relative_to(root):
        start = root
    for match in BIB_COMMAND_RE.finditer(source):
        found.commands = True
        for name in (part.strip() for part in match.group(2).split(",")):
            if not name:
                continue
            reason = None
            if root is None:
                reason = "no base dir given"
            elif Path(name).is_absolute() or name.startswith("~"):
                reason = "absolute path"
            else:
                file_name = name if name.lower().endswith(".bib") else f"{name}.bib"
                candidates = [(folder / file_name).resolve() for folder in dict.fromkeys((start, root))]
                resolved = next((c for c in candidates if c.is_relative_to(root) and c.is_file()), candidates[0])
                if not resolved.is_relative_to(root):
                    reason = "outside base dir"
                elif not resolved.is_file():
                    reason = "missing"
                elif resolved.stat().st_size > MAX_BIB_BYTES:
                    reason = f"larger than {MAX_BIB_BYTES // (1024 * 1024)} MB"
                elif len(found.paths) >= MAX_BIB_FILES:
                    reason = f"more than {MAX_BIB_FILES} bibliography files"
                elif resolved not in found.paths:
                    found.paths.append(resolved)
            if reason:
                found.warnings.append(
                    ConversionWarning("missing_bibliography", f"\\{match.group(1)}{{{name}}}: {reason}")
                )
    return found


_PANDOC_BIB_ERROR_RE = re.compile(r"Error reading bibliography file (.+?):\s*\(line (\d+), column \d+\)", re.DOTALL)


def failing_entry(stderr: str) -> tuple[str, int] | None:
    """(file, line) from pandoc's "Error reading bibliography file" message."""
    match = _PANDOC_BIB_ERROR_RE.search(stderr)
    return (match.group(1).strip(), int(match.group(2))) if match else None


def drop_entry_at_line(text: str, line: int) -> tuple[str, str] | None:
    """Remove the entry that contains ``line`` (1-based); return (text, entry head)."""
    offset = sum(len(part) + 1 for part in text.split("\n")[: max(line - 1, 0)])
    starts = [m.start() for m in _ENTRY_START_RE.finditer(text)]
    before = [start for start in starts if start <= offset]
    if not before:
        return None
    start = before[-1]
    following = [s for s in starts if s > start]
    end = following[0] if following else len(text)
    head = text[start:end].strip().splitlines()[0][:60]
    return text[:start] + text[end:], head


class BibCopies:
    """Sanitised temporary copies of ``.bib`` files that pandoc reads.

    :meth:`run` retries a pandoc call, dropping each entry pandoc reports as
    unparseable, so one bad entry costs one reference instead of all of them.
    CSL JSON files are passed through unchanged.
    """

    def __init__(self, paths: list[Path], folder: Path, warnings: WarningLog) -> None:
        self.warnings = warnings
        self.copies: dict[str, str] = {}
        for index, path in enumerate(paths):
            if path.suffix.lower() != ".bib":
                self.copies[str(path)] = path.name
                continue
            text, problems = sanitize_bib(path.read_text(encoding="utf-8", errors="replace"))
            for problem in problems:
                warnings.add("bibliography", f"{path.name}: {problem}")
            copy = folder / f"bibliography-{index}.bib"
            copy.write_text(text, encoding="utf-8")
            self.copies[str(copy)] = path.name

    def args(self) -> list[str]:
        return [f"--bibliography={copy}" for copy in self.copies]

    def _drop_failing_entry(self, stderr: str) -> bool:
        failure = failing_entry(stderr)
        if failure is None:
            return False
        name, line = failure
        copy = next((c for c in self.copies if c == name or Path(c).name == Path(name).name), None)
        if copy is None or not copy.endswith(".bib") or Path(copy).name == self.copies[copy]:
            return False
        dropped = drop_entry_at_line(Path(copy).read_text(encoding="utf-8"), line)
        if dropped is None:
            return False
        text, head = dropped
        Path(copy).write_text(text, encoding="utf-8")
        self.warnings.add("bibliography", f"{self.copies[copy]}: {head}: pandoc could not parse this entry")
        return True

    def run(self, call: Callable[[list[str]], T]) -> T | None:
        """``call(bibliography_args)``; None when pandoc still cannot read them."""
        for _ in range(MAX_BIB_RETRIES):
            try:
                return call(self.args())
            except ConversionError as exc:
                if "bibliography" not in str(exc).lower():
                    raise
                if not self._drop_failing_entry(exc.stderr or str(exc)):
                    return None
        return None

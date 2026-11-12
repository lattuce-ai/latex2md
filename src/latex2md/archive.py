"""Unpack arXiv-style source archives safely.

arXiv e-prints arrive as a tar.gz, a zip, a single gzip'd ``.tex`` or a bare
``.tex``. Archives are hostile input: members can be named ``../../etc/x`` or
``/abs/path``, be symlinks or devices, or decompress to terabytes. So members
are extracted into a private temporary folder with path containment, only
regular files are written, and every limit is enforced on the bytes actually
produced while streaming (headers can lie about sizes).
"""
from __future__ import annotations

import bz2
import gzip
import io
import json
import lzma
import re
import stat
import tarfile
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import IO

from latex2md.comments import strip_comments
from latex2md.pandoc import ConversionError

_CHUNK = 64 * 1024
_PREFERRED_STEMS = ("main", "paper", "ms")
_DOCUMENTCLASS_RE = re.compile(r"\\documentclass\b")
_BEGIN_DOCUMENT_RE = re.compile(r"\\begin\s*\{document\}")
# A compression ratio is only meaningful once enough output exists; tiny
# files of whitespace legitimately compress 1000:1.
_RATIO_GRACE_BYTES = 1024 * 1024


class ArchiveError(ConversionError):
    """The archive is invalid, has no ``.tex`` file, or exceeds a limit."""


@dataclass(frozen=True)
class ArchiveLimits:
    """Caps applied while extracting an archive."""

    max_total_bytes: int = 200 * 1024 * 1024
    max_members: int = 2000
    max_file_bytes: int = 50 * 1024 * 1024
    max_ratio: float = 100.0


@dataclass
class ExtractedArchive:
    root: Path
    main_tex: Path
    skipped: list[str] = field(default_factory=list)


class _Writer:
    """Writes members under ``root`` and enforces the limits on real bytes."""

    def __init__(self, root: Path, limits: ArchiveLimits, compressed_size: int) -> None:
        self.root = root
        self.limits = limits
        self.compressed_size = max(compressed_size, 1)
        self.total = 0
        self.members = 0
        self.skipped: list[str] = []

    def count_member(self) -> None:
        self.members += 1
        if self.members > self.limits.max_members:
            raise ArchiveError(f"archive has more than {self.limits.max_members} members")

    def account(self, size: int) -> None:
        self.total += size
        if self.total > self.limits.max_total_bytes:
            raise ArchiveError(f"archive expands to more than {self.limits.max_total_bytes} bytes")
        ratio = self.total / self.compressed_size
        if self.total > _RATIO_GRACE_BYTES and ratio > self.limits.max_ratio:
            raise ArchiveError(f"archive compression ratio exceeds {self.limits.max_ratio:g}:1")

    def target(self, name: str) -> Path | None:
        """The extraction path for ``name``, or None when it would escape."""
        name = name.replace("\\", "/")
        pure = PurePosixPath(name)
        if pure.is_absolute() or re.match(r"^[A-Za-z]:", name) or ".." in pure.parts:
            return None
        parts = [part for part in pure.parts if part not in ("", ".")]
        if not parts:
            return None
        path = self.root.joinpath(*parts)
        parent = path.parent.resolve()
        if not parent.is_relative_to(self.root) and parent != self.root:
            return None
        return path

    def write(self, name: str, read: Callable[[int], bytes]) -> None:
        path = self.target(name)
        if path is None:
            self.skipped.append(f"{name}: path outside the archive root")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.parent.resolve().is_relative_to(self.root) or path.is_symlink():
            self.skipped.append(f"{name}: path outside the archive root")
            return
        size = 0
        with open(path, "wb") as out:
            while chunk := read(_CHUNK):
                size += len(chunk)
                if size > self.limits.max_file_bytes:
                    raise ArchiveError(f"{name} is larger than {self.limits.max_file_bytes} bytes")
                self.account(len(chunk))
                out.write(chunk)
        path.chmod(0o600)


def _extract_zip(data: bytes, writer: _Writer) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError) as exc:
        raise ArchiveError(f"invalid zip archive: {exc}") from exc
    with archive:
        for info in archive.infolist():
            writer.count_member()
            mode = info.external_attr >> 16
            if info.is_dir():
                continue
            if stat.S_IFMT(mode) and not stat.S_ISREG(mode):
                writer.skipped.append(f"{info.filename}: not a regular file")
                continue
            if info.flag_bits & 0x1:
                writer.skipped.append(f"{info.filename}: encrypted")
                continue
            try:
                with archive.open(info) as member:
                    writer.write(info.filename, member.read)
            except (zipfile.BadZipFile, NotImplementedError, EOFError, OSError) as exc:
                raise ArchiveError(f"invalid zip member {info.filename}: {exc}") from exc


def _extract_tar(stream: IO[bytes], writer: _Writer) -> None:
    try:
        with tarfile.open(fileobj=stream, mode="r:") as archive:
            for member in archive:
                writer.count_member()
                if member.isdir():
                    continue
                if not member.isfile():
                    writer.skipped.append(f"{member.name}: not a regular file")
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    continue
                with handle:
                    writer.write(member.name, handle.read)
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise ArchiveError(f"invalid tar archive: {exc}") from exc


def _decompress(data: bytes, opener: Callable[[IO[bytes]], IO[bytes]], writer: _Writer, spool: IO[bytes]) -> None:
    """Decompress a single stream into ``spool``, capped like the archive itself."""
    # A tar adds 512-byte headers and padding around the files it holds.
    cap = writer.limits.max_total_bytes + 1024 * (writer.limits.max_members + 4)
    produced = 0
    try:
        with opener(io.BytesIO(data)) as stream:
            while chunk := stream.read(_CHUNK):
                produced += len(chunk)
                if produced > cap:
                    raise ArchiveError(f"archive expands to more than {writer.limits.max_total_bytes} bytes")
                if produced > _RATIO_GRACE_BYTES and produced / writer.compressed_size > writer.limits.max_ratio:
                    raise ArchiveError(f"archive compression ratio exceeds {writer.limits.max_ratio:g}:1")
                spool.write(chunk)
    except (OSError, EOFError, lzma.LZMAError, ValueError) as exc:
        raise ArchiveError(f"invalid compressed data: {exc}") from exc
    spool.seek(0)


def _is_tar(head: bytes) -> bool:
    return len(head) >= 262 and head[257:262] == b"ustar"


_COMPRESSORS: tuple[tuple[bytes, Callable[[IO[bytes]], IO[bytes]]], ...] = (
    (b"\x1f\x8b", gzip.open),
    (b"BZh", bz2.open),
    (b"\xfd7zXZ\x00", lzma.open),
)


def _write_single_tex(read: Callable[[int], bytes], writer: _Writer) -> None:
    writer.count_member()
    writer.write("main.tex", read)


def _unpack(data: bytes, writer: _Writer) -> None:
    if data.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        _extract_zip(data, writer)
        return
    for magic, opener in _COMPRESSORS:
        if data.startswith(magic):
            with tempfile.TemporaryFile() as spool:
                _decompress(data, opener, writer, spool)
                if _is_tar(spool.read(512)):
                    spool.seek(0)
                    _extract_tar(spool, writer)
                else:
                    spool.seek(0)
                    _write_single_tex(spool.read, writer)
            return
    if _is_tar(data[:512]):
        _extract_tar(io.BytesIO(data), writer)
        return
    if data.startswith(b"%PDF"):
        # arXiv serves the PDF as the "e-print" of submissions without source.
        raise ArchiveError("this is a PDF, not LaTeX source")
    if b"\x00" in data[:4096]:
        raise ArchiveError("not a zip, tar, gzip or .tex file")
    _write_single_tex(io.BytesIO(data).read, writer)


def _readme_toplevel(root: Path) -> Path | None:
    """arXiv's ``00README.json`` may name the top-level file explicitly."""
    readme = root / "00README.json"
    if not readme.is_file() or readme.stat().st_size > 1024 * 1024:
        return None
    try:
        sources = json.loads(readme.read_text(encoding="utf-8")).get("sources", [])
        for source in sources:
            if source.get("usage") == "toplevel":
                candidate = (root / str(source.get("filename", ""))).resolve()
                if candidate.is_relative_to(root) and candidate.is_file() and candidate.suffix == ".tex":
                    return candidate
    except (ValueError, AttributeError, TypeError):
        return None
    return None


def find_main_tex(root: Path) -> Path:
    """Pick the file LaTeX would be run on.

    A ``00README.json`` toplevel entry wins. Otherwise a ``.tex`` with both
    ``\\documentclass`` and ``\\begin{document}``, preferring ``main``/``paper``/
    ``ms``, else the shallowest; then those conventional names, then the
    shallowest ``.tex`` at all.
    """
    root = root.resolve()
    if (readme := _readme_toplevel(root)) is not None:
        return readme
    tex_files = sorted(
        (p for p in root.rglob("*") if p.suffix.lower() == ".tex" and p.is_file() and not p.is_symlink()),
        key=lambda p: (len(p.relative_to(root).parts), str(p.relative_to(root)).lower()),
    )
    if not tex_files:
        raise ArchiveError("archive contains no .tex file")

    def is_document(path: Path) -> bool:
        text = strip_comments(path.read_text(encoding="utf-8", errors="replace"))
        return bool(_DOCUMENTCLASS_RE.search(text) and _BEGIN_DOCUMENT_RE.search(text))

    def preferred(paths: list[Path]) -> Path | None:
        return next((p for p in paths if p.stem.lower() in _PREFERRED_STEMS), None)

    documents = [p for p in tex_files if is_document(p)]
    if documents:
        return preferred(documents) or documents[0]
    return preferred(tex_files) or tex_files[0]


@contextmanager
def extract_archive(data: bytes, *, limits: ArchiveLimits | None = None) -> Iterator[ExtractedArchive]:
    """Like :func:`open_latex_archive`, also reporting skipped members."""
    limits = limits or ArchiveLimits()
    with tempfile.TemporaryDirectory(prefix="latex2md-") as tmp:
        root = Path(tmp).resolve()
        writer = _Writer(root, limits, len(data))
        _unpack(data, writer)
        yield ExtractedArchive(root, find_main_tex(root), writer.skipped)


@contextmanager
def open_latex_archive(data: bytes, *, limits: ArchiveLimits | None = None) -> Iterator[tuple[Path, Path]]:
    """Extract an arXiv-style source archive into a private temporary folder.

    Accepts zip, tar (optionally gzip/bzip2/xz compressed), a single gzip'd
    ``.tex`` and a bare ``.tex``. Yields ``(root_dir, main_tex)``; the folder
    is deleted when the ``with`` block ends. Symlinks, hard links, devices and
    members whose path would leave the folder are skipped. Raises
    :class:`ArchiveError` when the data is invalid or exceeds ``limits``.
    """
    with extract_archive(data, limits=limits) as extracted:
        yield extracted.root, extracted.main_tex

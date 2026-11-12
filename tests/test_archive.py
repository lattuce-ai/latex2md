import gzip
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest
from conftest import FIXTURES, requires_pandoc

from latex2md import (
    ArchiveError,
    ArchiveLimits,
    ConversionError,
    cli,
    convert_latex_archive_to_md,
    flatten_latex,
    latex_archive_to_md,
    latex_file_to_md,
    open_latex_archive,
)

PAPER = FIXTURES / "paper"
DOC = "\\documentclass{article}\n\\begin{document}\n{body}\n\\end{document}\n"


def doc(body: str) -> str:
    return DOC.replace("{body}", body)


def make_zip(files: dict[str, str | bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def make_tar(files: dict[str, str | bytes], *, gz: bool = True, extra: list[tarfile.TarInfo] = ()) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz" if gz else "w") as archive:
        for name, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        for info in extra:
            archive.addfile(info)
    return buffer.getvalue()


def paper_files() -> dict[str, bytes]:
    return {str(p.relative_to(PAPER)): p.read_bytes() for p in PAPER.rglob("*") if p.is_file()}


def extracted_names(data: bytes, **kwargs) -> tuple[set[str], str]:
    with open_latex_archive(data, **kwargs) as (root, main_tex):
        names = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
        return names, str(main_tex.relative_to(root))


def _fails(data: bytes, *, match: str | None = None, limits: ArchiveLimits | None = None) -> None:
    with pytest.raises(ArchiveError, match=match), open_latex_archive(data, limits=limits):
        pass


# --- formats ---------------------------------------------------------------


@pytest.mark.parametrize("builder", [make_zip, make_tar, lambda f: make_tar(f, gz=False)])
def test_archive_formats(builder):
    names, main = extracted_names(builder({"paper.tex": doc("x"), "sec/a.tex": "A"}))
    assert names == {"paper.tex", "sec/a.tex"}
    assert main == "paper.tex"


def test_single_gzipped_tex_and_raw_tex():
    assert extracted_names(gzip.compress(doc("x").encode())) == ({"main.tex"}, "main.tex")
    assert extracted_names(doc("x").encode()) == ({"main.tex"}, "main.tex")


def test_temp_dir_is_private_and_removed():
    with open_latex_archive(make_zip({"main.tex": doc("x")})) as (root, main_tex):
        assert root.stat().st_mode & 0o077 == 0
        assert main_tex.read_text().startswith("\\documentclass")
    assert not root.exists()


def test_binary_garbage_is_rejected():
    _fails(b"\x00\x01\x02garbage")
    _fails(b"\x1f\x8b\x08\x00broken", match="invalid")
    _fails(b"%PDF-1.6\n...", match="PDF, not LaTeX source")
    assert issubclass(ArchiveError, ConversionError)


def test_archive_without_tex_is_rejected():
    _fails(make_zip({"README.md": "hi"}), match="no .tex")


# --- main file selection ------------------------------------------------------


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({"a.tex": doc("a"), "ms.tex": doc("ms"), "b.tex": "fragment"}, "ms.tex"),
        ({"zeta.tex": doc("z"), "alpha.tex": "\\section{x}"}, "zeta.tex"),
        ({"x.tex": doc("x"), "sub/main.tex": doc("m")}, "sub/main.tex"),
        ({"a.tex": "frag", "paper.tex": "frag"}, "paper.tex"),
        ({"b.tex": "frag", "a.tex": "frag"}, "a.tex"),
        # A \documentclass that is commented out does not count.
        ({"a.tex": "% \\documentclass{x}\\begin{document}", "b.tex": doc("b")}, "b.tex"),
        (
            {
                "main.tex": doc("m"),
                "other.tex": doc("o"),
                "00README.json": json.dumps({"sources": [{"filename": "other.tex", "usage": "toplevel"}]}),
            },
            "other.tex",
        ),
    ],
)
def test_main_file_selection(files, expected):
    assert extracted_names(make_zip(files))[1] == expected


# --- hostile archives ---------------------------------------------------------


def test_path_traversal_and_absolute_members_are_skipped(tmp_path):
    data = make_tar({"main.tex": doc("x"), "../evil.tex": "E", "/abs/evil.tex": "E", "a/../../evil2.tex": "E"})
    names, _ = extracted_names(data)
    assert names == {"main.tex"}
    zipped = make_zip({"main.tex": doc("x"), "../evil.tex": "E", "C:\\evil.tex": "E", "..\\evil3.tex": "E"})
    assert extracted_names(zipped)[0] == {"main.tex"}
    assert not (tmp_path.parent / "evil.tex").exists()


def test_links_and_devices_are_skipped():
    symlink = tarfile.TarInfo("link.tex")
    symlink.type = tarfile.SYMTYPE
    symlink.linkname = "/etc/passwd"
    hardlink = tarfile.TarInfo("hard.tex")
    hardlink.type = tarfile.LNKTYPE
    hardlink.linkname = "main.tex"
    device = tarfile.TarInfo("dev.tex")
    device.type = tarfile.CHRTYPE
    fifo = tarfile.TarInfo("fifo.tex")
    fifo.type = tarfile.FIFOTYPE
    data = make_tar({"main.tex": doc("\\input{link}")}, extra=[symlink, hardlink, device, fifo])
    assert extracted_names(data)[0] == {"main.tex"}


def test_zip_symlink_member_is_skipped():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("main.tex", doc("x"))
        info = zipfile.ZipInfo("link.tex")
        info.external_attr = (0o120777 << 16)
        archive.writestr(info, "/etc/passwd")
    assert extracted_names(buffer.getvalue())[0] == {"main.tex"}


def test_symlinked_member_path_does_not_escape(tmp_path):
    """A symlink member followed by a file "through" it must not write outside."""
    symlink = tarfile.TarInfo("dir")
    symlink.type = tarfile.SYMTYPE
    symlink.linkname = str(tmp_path)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        archive.addfile(symlink)
        data = b"pwned"
        info = tarfile.TarInfo("dir/pwned.tex")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
        main = doc("x").encode()
        info = tarfile.TarInfo("main.tex")
        info.size = len(main)
        archive.addfile(info, io.BytesIO(main))
    with open_latex_archive(buffer.getvalue()):
        pass
    assert not (tmp_path / "pwned.tex").exists()


def test_zip_bomb_hits_ratio_limit():
    bomb = make_zip({"main.tex": doc("x"), "bomb.tex": b"0" * (20 * 1024 * 1024)})
    _fails(bomb, match="ratio")


def test_tar_bomb_hits_total_limit_while_streaming():
    data = make_tar({"main.tex": doc("x"), "big.tex": b"0" * 3_000_000})
    limits = ArchiveLimits(max_total_bytes=1_000_000, max_ratio=10**9)
    _fails(data, limits=limits, match="more than 1000000 bytes")


def test_gzipped_bomb_is_capped_before_extraction():
    data = gzip.compress(b"\\documentclass{x}" + b" " * 5_000_000)
    limits = ArchiveLimits(max_total_bytes=1_000_000, max_ratio=10**9)
    _fails(data, limits=limits, match="more than")


def test_per_file_and_member_count_limits():
    _fails(make_zip({"main.tex": doc("x")}), limits=ArchiveLimits(max_file_bytes=10), match="larger than 10 bytes")
    many = make_zip({f"f{i}.tex": "x" for i in range(30)})
    _fails(many, limits=ArchiveLimits(max_members=20), match="more than 20 members")


def test_archive_limits_is_frozen():
    with pytest.raises(AttributeError):
        ArchiveLimits().max_members = 1  # type: ignore[misc]


# --- conversion ---------------------------------------------------------------


@requires_pandoc
@pytest.mark.parametrize("builder", [make_zip, make_tar])
def test_archive_converts_like_the_folder(builder):
    expected = latex_file_to_md(PAPER / "main.tex")
    assert latex_archive_to_md(builder(paper_files())) == expected


@requires_pandoc
def test_archive_result_reports_skipped_members():
    symlink = tarfile.TarInfo("link.tex")
    symlink.type = tarfile.SYMTYPE
    symlink.linkname = "/etc/passwd"
    result = convert_latex_archive_to_md(make_tar({"main.tex": doc("Hi")}, extra=[symlink]))
    assert result.text == "Hi\n"
    assert [(w.kind, w.message) for w in result.warnings] == [("skipped_member", "link.tex: not a regular file")]


# --- flatten ------------------------------------------------------------------


def test_flatten_latex_file():
    flat = flatten_latex(PAPER / "main.tex")
    assert "\\section{Introduction}" in flat and "\\section{Method}" in flat
    assert "def score(q, k):" in flat
    assert "\\input" not in flat and "% Sections" not in flat
    assert "$\\ce{2H2 + O2 -> 2H2O}$" in flat


def test_flatten_latex_text_and_bbl(tmp_path):
    (tmp_path / "a.tex").write_text("AAA", encoding="utf-8")
    assert flatten_latex("x \\input{a} % c", base_dir=tmp_path) == "x \nAAA\n "
    assert flatten_latex("x \\input{a}") == "x "
    bbl = "\\begin{thebibliography}{1}\\bibitem{k} K.\\end{thebibliography}"
    assert flatten_latex("\\bibliography{refs}", bbl=bbl) == bbl


def test_flatten_never_reads_outside(tmp_path):
    secret = tmp_path / "secret.tex"
    secret.write_text("TOP-SECRET", encoding="utf-8")
    root = tmp_path / "p"
    root.mkdir()
    (root / "main.tex").write_text("\\input{../secret} \\input{" + str(secret) + "}", encoding="utf-8")
    assert "TOP-SECRET" not in flatten_latex(Path(root / "main.tex"))


def test_cli_flatten(tmp_path, capsys):
    assert cli.main(["flatten", str(PAPER / "main.tex")]) == 0
    captured = capsys.readouterr()
    assert "\\section{Method}" in captured.out
    assert "skipped_include" in captured.err
    archive = tmp_path / "paper.zip"
    archive.write_bytes(make_zip(paper_files()))
    assert cli.main(["flatten", str(archive), "-o", str(tmp_path / "flat.tex")]) == 0
    assert "\\section{Method}" in (tmp_path / "flat.tex").read_text(encoding="utf-8")


@requires_pandoc
@pytest.mark.parametrize("suffix", [".zip", ".tar.gz", ".tgz", ".tar"])
def test_cli_to_md_archive(tmp_path, capsys, suffix):
    archive = tmp_path / f"paper{suffix}"
    files = paper_files()
    archive.write_bytes(make_zip(files) if suffix == ".zip" else make_tar(files, gz=suffix != ".tar"))
    assert cli.main(["to-md", str(archive)]) == 0
    assert "# Method" in capsys.readouterr().out
    assert cli.main(["auto", str(archive)]) == 0

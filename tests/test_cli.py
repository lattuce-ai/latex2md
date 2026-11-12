import io

import pytest
from conftest import FIXTURES, requires_pandoc

from latex2md import cli
from latex2md.pandoc import ConversionError


@requires_pandoc
def test_to_latex_file_to_stdout(capsys):
    assert cli.main(["to-latex", str(FIXTURES / "sample.md")]) == 0
    assert "\\section{Introduction}" in capsys.readouterr().out


@requires_pandoc
def test_to_md_writes_output_file(tmp_path):
    out = tmp_path / "out.md"
    assert cli.main(["to-md", str(FIXTURES / "sample.tex"), "-o", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Introduction")


@requires_pandoc
def test_auto_detects_direction(capsys):
    assert cli.main(["auto", str(FIXTURES / "sample.tex")]) == 0
    assert capsys.readouterr().out.startswith("# Introduction")


@requires_pandoc
def test_stdin(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("**hi**"))
    assert cli.main(["to-latex"]) == 0
    assert capsys.readouterr().out == "\\textbf{hi}\n"


@requires_pandoc
def test_standalone_flag(capsys):
    assert cli.main(["to-latex", "--standalone", str(FIXTURES / "sample.md")]) == 0
    assert "\\begin{document}" in capsys.readouterr().out


def test_auto_rejects_unknown_extension(tmp_path, capsys):
    path = tmp_path / "notes.txt"
    path.write_text("x", encoding="utf-8")
    assert cli.main(["auto", str(path)]) == 1
    assert "cannot tell the input format" in capsys.readouterr().err


def test_missing_input_file(capsys):
    assert cli.main(["to-md", "does-not-exist.tex"]) == 1
    assert "latex2md:" in capsys.readouterr().err


def test_missing_pandoc_is_reported(monkeypatch, capsys):
    monkeypatch.setenv("LATEX2MD_PANDOC", "")
    monkeypatch.setattr("shutil.which", lambda _name: None)
    with pytest.raises(ConversionError, match="pandoc is not installed"):
        from latex2md import md_to_latex

        md_to_latex("x")
    monkeypatch.setattr("sys.stdin", io.StringIO("x"))
    assert cli.main(["to-latex"]) == 1
    assert "pandoc is not installed" in capsys.readouterr().err


def test_pandoc_failure_raises(monkeypatch, tmp_path):
    fake = tmp_path / "pandoc"
    fake.write_text("#!/bin/sh\necho boom >&2\nexit 3\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("LATEX2MD_PANDOC", str(fake))
    from latex2md import latex_to_md

    with pytest.raises(ConversionError, match="boom") as info:
        latex_to_md("x")
    assert "boom" in info.value.stderr

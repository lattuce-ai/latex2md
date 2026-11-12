from pathlib import Path

from conftest import FIXTURES, requires_pandoc

from latex2md import (
    ConversionResult,
    ConversionWarning,
    cli,
    convert_latex_file_to_md,
    convert_latex_to_md,
    convert_md_to_latex,
)
from latex2md.includes import expand_includes
from latex2md.pandoc import pandoc_messages

PAPER = FIXTURES / "paper"


def _project(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp_path


def _skips(src: str, root: Path | None) -> list[str]:
    warnings: list[ConversionWarning] = []
    expand_includes(src, root, warnings=warnings)
    assert all(w.kind == "skipped_include" for w in warnings)
    return [w.message for w in warnings]


def test_skipped_include_reasons(tmp_path):
    root = _project(tmp_path / "p", {"a.tex": "A \\input{b}", "b.tex": "B \\input{a}"})
    (tmp_path / "secret.tex").write_text("S", encoding="utf-8")
    (root / "link.tex").symlink_to(tmp_path / "secret.tex")
    messages = _skips("\\input{/etc/passwd} \\input{../secret} \\input{link} \\input{nope} \\input{a}", root)
    assert messages == [
        "\\input{/etc/passwd}: absolute path",
        "\\input{../secret}: outside base dir",
        "\\input{link}: outside base dir",
        "\\input{nope}: missing",
        "\\input{a}: include cycle",
    ]


def test_skipped_include_depth_and_budget(tmp_path, monkeypatch):
    files = {f"f{i}.tex": f"\\input{{f{i + 1}}}" for i in range(20)}
    root = _project(tmp_path, {**files, "big.tex": "x" * 100})
    assert any("nested deeper than 16" in m for m in _skips("\\input{f0}", root))
    monkeypatch.setattr("latex2md.includes.MAX_INCLUDED_BYTES", 10)
    assert _skips("\\input{big}", root) == ["\\input{big}: size budget of 0 MB exceeded"]


def test_skipped_include_without_base_dir():
    assert _skips("\\include{x} \\lstinputlisting{y.py}", None) == [
        "\\lstinputlisting{y.py}: no base dir given",
        "\\include{x}: no base dir given",
    ]


@requires_pandoc
def test_fixture_paper_reports_hostile_includes():
    result = convert_latex_file_to_md(PAPER / "main.tex")
    assert isinstance(result, ConversionResult)
    kinds = {(w.kind, w.message) for w in result.warnings}
    assert ("skipped_include", "\\input{/etc/hostname}: absolute path") in kinds
    assert ("skipped_include", "\\input{../../../../etc/hostname}: outside base dir") in kinds
    # Layout commands such as \centering and \maketitle are not reported.
    assert not [w for w in result.warnings if w.kind == "unknown_command"]


@requires_pandoc
def test_unknown_command_and_environment():
    result = convert_latex_to_md("\\begin{document}\n\\foo{x} \\begin{weird}kept\\end{weird}\n\\end{document}")
    assert "kept" in result.text
    unknown = [(w.kind, w.message) for w in result.warnings]
    assert ("unknown_command", "\\foo{x}") in unknown
    assert ("unknown_environment", "\\begin{weird}") in unknown
    assert all(w.location and "line 2" in w.location for w in result.warnings)


@requires_pandoc
def test_preamble_skips_are_not_reported():
    result = convert_latex_to_md("\\foo\n\\begin{document}\nHi\n\\end{document}")
    assert result.warnings == []


@requires_pandoc
def test_missing_bibliography():
    result = convert_latex_to_md("Text \\cite{k}.\n\\bibliography{refs}")
    assert [w.kind for w in result.warnings] == ["missing_bibliography"]


@requires_pandoc
def test_other_pandoc_warnings():
    result = convert_md_to_latex("[a][x]\n\n[x]: https://a.example\n[x]: https://b.example\n")
    assert [w.kind for w in result.warnings] == ["pandoc"]
    assert "Duplicate link reference" in result.warnings[0].message


def test_pandoc_messages_parser_joins_continuation_lines():
    stderr = "[WARNING] Could not convert\n  some math\n[INFO] Not interesting\n"
    assert pandoc_messages(stderr) == [ConversionWarning("pandoc", "Could not convert some math")]


@requires_pandoc
def test_str_api_unchanged():
    from latex2md import latex_to_md, md_to_latex

    assert latex_to_md("\\foo{x} hi") == "hi\n"
    assert md_to_latex("hi") == "hi\n"


@requires_pandoc
def test_cli_prints_warnings_and_strict_fails(capsys):
    assert cli.main(["to-md", str(PAPER / "main.tex")]) == 0
    assert "warning: skipped_include" in capsys.readouterr().err
    assert cli.main(["to-md", "--strict", str(PAPER / "main.tex")]) == 1
    capsys.readouterr()
    assert cli.main(["to-md", "--strict", "--quiet", str(FIXTURES / "sample.tex")]) == 0
    assert capsys.readouterr().err == ""

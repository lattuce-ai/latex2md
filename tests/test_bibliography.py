import io
import shutil
import tarfile
from pathlib import Path

import pytest
from conftest import FIXTURES, requires_pandoc

from latex2md import (
    ConversionError,
    cli,
    convert_latex_archive_to_md,
    convert_latex_file_to_md,
    convert_latex_to_md,
    latex_file_to_md,
    latex_to_md,
)
from latex2md.bibliography import drop_entry_at_line, sanitize_bib

BIB = FIXTURES / "bib"
pytestmark = requires_pandoc

KNUTH = "- Knuth, Donald E. 1984. *The TeXbook*. Addison-Wesley."
LOVELACE = '- Lovelace, Ada. 1843. "Notes on the Analytical Engine." *Scientific Memoirs*.'


@pytest.fixture
def project(tmp_path: Path) -> Path:
    shutil.copytree(BIB, tmp_path / "p")
    return tmp_path / "p"


def test_bib_renders_references_where_bibliography_was(project):
    result = convert_latex_file_to_md(project / "main.tex")
    md = result.text
    assert "As shown by [@knuth1984] and @lovelace1843, see also [@knuth1984 p. 3]." in md
    assert f"# References\n\n{KNUTH}\n{LOVELACE}\n\n# Extra\n\nAfter the references." in md
    assert "bibliography:" not in md and "csl:" not in md  # temporary paths stay out of front matter
    assert [(w.kind, w.message) for w in result.warnings] == [
        ("bibliography", "refs.bib: @article{broken,: unbalanced braces"),
        ("bibliography", "refs.bib: @article{nocomma,: pandoc could not parse this entry"),
    ]


def test_cite_style_rendered(project):
    md = latex_file_to_md(project / "main.tex", cite_style="rendered")
    assert "As shown by (Knuth 1984) and Lovelace (1843), see also (Knuth 1984, 3)." in md
    assert "[@" not in md


def test_cite_style_is_validated(project):
    with pytest.raises(ValueError, match="cite_style"):
        latex_file_to_md(project / "main.tex", cite_style="fancy")  # type: ignore[arg-type]


def test_csl_style(project):
    md = latex_file_to_md(project / "main.tex", csl=project / "numeric.csl", cite_style="rendered")
    assert "As shown by \\[1\\] and \\[2\\]" in md
    assert "- \\[1\\] Donald E. Knuth, The TeXbook" in md


def test_csl_must_be_inside_base_dir_and_a_file(project, tmp_path):
    outside = tmp_path / "outside.csl"
    shutil.copy(project / "numeric.csl", outside)
    with pytest.raises(ConversionError, match="outside"):
        latex_file_to_md(project / "main.tex", csl=outside)
    (project / "link.csl").symlink_to(outside)
    with pytest.raises(ConversionError, match="outside"):
        latex_file_to_md(project / "main.tex", csl=project / "link.csl")
    with pytest.raises(ConversionError, match="not an existing file"):
        latex_file_to_md(project / "main.tex", csl=project / "missing.csl")
    with pytest.raises(ConversionError, match="not an existing file"):
        latex_file_to_md(project / "main.tex", csl=project)


def test_bbl_wins_over_bib(project):
    (project / "main.bbl").write_text(
        "\\begin{thebibliography}{1}\\bibitem{knuth1984} From the bbl.\\end{thebibliography}", encoding="utf-8"
    )
    md = latex_file_to_md(project / "main.tex")
    assert "- From the bbl." in md and "Addison-Wesley" not in md


def test_text_input_with_base_dir_uses_bib(project):
    md = latex_to_md("Text \\cite{knuth1984}.\n\\bibliography{refs}", base_dir=project)
    assert md.startswith("Text [@knuth1984].\n\n# References\n\n" + KNUTH)


def test_biblatex_addbibresource_and_printbibliography(project):
    src = "\\addbibresource{refs.bib}\\begin{document}\\cite{lovelace1843}\\printbibliography\\section{After}\\end{document}"
    md = latex_to_md(src, base_dir=project)
    assert f"[@lovelace1843]\n\n# References\n\n{LOVELACE}\n\n# After" in md


def test_hostile_bibliography_paths_are_not_read(tmp_path):
    secret = tmp_path / "secret.bib"
    secret.write_text("@misc{leak, title={TOP-SECRET}}", encoding="utf-8")
    root = tmp_path / "p"
    root.mkdir()
    (root / "link.bib").symlink_to(secret)
    src = f"\\cite{{leak}}\\bibliography{{../secret,{secret},link,nothere}}"
    result = convert_latex_to_md(src, base_dir=root, cite_style="rendered")
    assert "TOP-SECRET" not in result.text
    assert [w.message for w in result.warnings if w.kind == "missing_bibliography"] == [
        "\\bibliography{../secret}: outside base dir",
        f"\\bibliography{{{secret}}}: absolute path",
        "\\bibliography{link}: outside base dir",
        "\\bibliography{nothere}: missing",
    ]


def test_oversized_bib_is_refused(project, monkeypatch):
    monkeypatch.setattr("latex2md.bibliography.MAX_BIB_BYTES", 10)
    result = convert_latex_file_to_md(project / "main.tex")
    assert ("missing_bibliography", "\\bibliography{refs}: larger than 0 MB") in [
        (w.kind, w.message) for w in result.warnings
    ]
    assert "# References" not in result.text


def test_unreadable_bib_falls_back_without_citeproc(project, monkeypatch):
    monkeypatch.setattr("latex2md.bibliography.BibCopies._drop_failing_entry", lambda *args: False)
    result = convert_latex_file_to_md(project / "main.tex")
    assert "As shown by [@knuth1984]" in result.text
    assert "pandoc could not read the bibliography; citations stay as [@key]" in [w.message for w in result.warnings]


def test_bib_in_archive(project):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        archive.add(project / "main.tex", "main.tex")
        archive.add(project / "refs.bib", "refs.bib")
    result = convert_latex_archive_to_md(buffer.getvalue())
    assert KNUTH in result.text


def test_cli_bib_flags(project, capsys):
    assert cli.main(["to-md", str(project / "main.tex"), "--cite-style", "rendered", "--csl", str(project / "numeric.csl")]) == 0
    assert "As shown by \\[1\\]" in capsys.readouterr().out


def test_sanitize_bib():
    text, problems = sanitize_bib(
        "junk\n@comment{x}\n@string{a = {b}}\n@misc{ok, title={A {B} C}}\n@misc{bad, title={x}\n@misc(paren, title={y})\n@misc{, title={nokey}}\n"
    )
    assert text == "@string{a = {b}}\n\n@misc{ok, title={A {B} C}}\n\n@misc(paren, title={y})\n"
    assert problems == ["@misc{bad, title={x}: unbalanced braces", "@misc{, title={nokey}}: no citation key"]


def test_drop_entry_at_line():
    text = "@misc{a, title={1}}\n\n@misc{b,\n title={2}}\n\n@misc{c, title={3}}\n"
    assert drop_entry_at_line(text, 4) == ("@misc{a, title={1}}\n\n@misc{c, title={3}}\n", "@misc{b,")

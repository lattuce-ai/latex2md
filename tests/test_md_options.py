import base64
from pathlib import Path

import pytest
from conftest import FIXTURES, requires_pandoc

from latex2md import ConversionError, cli, convert_md_to_latex, md_to_latex

BIB = FIXTURES / "bib"
CITES = "See [@knuth1984; @lovelace1843] and @knuth1984."
pytestmark = requires_pandoc


# --- citations ------------------------------------------------------------------


def test_citations_cite_is_the_default():
    assert md_to_latex(CITES) == "See \\cite{knuth1984, lovelace1843} and \\citet{knuth1984}.\n"
    assert md_to_latex(CITES, citations="cite") == md_to_latex(CITES)


def test_citations_natbib():
    assert md_to_latex(CITES, citations="natbib") == "See \\citep{knuth1984, lovelace1843} and \\citet{knuth1984}.\n"


def test_citations_biblatex():
    assert md_to_latex(CITES, citations="biblatex") == (
        "See \\autocite{knuth1984,lovelace1843} and \\textcite{knuth1984}.\n"
    )


def test_citations_citeproc_fragment_has_plain_reference_list():
    result = convert_md_to_latex(CITES, citations="citeproc", bibliography=BIB / "refs.bib")
    assert result.text.startswith("See (Knuth 1984; Lovelace 1843) and Knuth (1984).\n\n\\section*{References}")
    assert "\\item\n  Knuth, Donald E. 1984. \\emph{The {TeX}book}. Addison-Wesley." in result.text
    assert "CSLReferences" not in result.text and "\\hypertarget" not in result.text
    assert {w.kind for w in result.warnings} == {"bibliography"}  # the fixture's two broken entries


def test_citations_citeproc_standalone_with_csl():
    out = md_to_latex(CITES, citations="citeproc", bibliography=BIB / "refs.bib", csl=BIB / "numeric.csl", standalone=True)
    assert "See {[}1, 2{]} and {[}1{]}." in out
    assert "\\begin{CSLReferences}" in out and "\\newenvironment{CSLReferences}" in out


def test_citations_citeproc_without_bibliography_warns():
    result = convert_md_to_latex(CITES, citations="citeproc")
    assert "missing_bibliography" in {w.kind for w in result.warnings}


def test_bibliography_named_in_standalone_preamble():
    natbib = md_to_latex(CITES, citations="natbib", bibliography=BIB / "refs.bib", standalone=True)
    assert f"\\bibliography{{{BIB / 'refs'}}}" in natbib
    biblatex = md_to_latex(CITES, citations="biblatex", bibliography=BIB / "refs.bib", standalone=True)
    assert f"\\addbibresource{{{BIB / 'refs.bib'}}}" in biblatex and "\\printbibliography" in biblatex


def test_invalid_citations_mode():
    with pytest.raises(ValueError, match="citations"):
        md_to_latex(CITES, citations="apa")  # type: ignore[arg-type]


# --- templates and variables -------------------------------------------------------


@pytest.fixture
def template(tmp_path: Path) -> Path:
    path = tmp_path / "res" / "letter.latex"
    path.parent.mkdir()
    path.write_text("% custom\n\\documentclass{$class$}\n\\begin{document}\nTo: $recipient$\n$body$\n\\end{document}\n")
    return path


def test_custom_template_with_variables(template):
    out = md_to_latex("Hello **world**.", template=template, variables={"class": "letter", "recipient": "Ada"})
    assert out == "% custom\n\\documentclass{letter}\n\\begin{document}\nTo: Ada\nHello \\textbf{world}.\n\\end{document}\n"


def test_template_must_be_inside_resource_dir_and_exist(template, tmp_path):
    md_to_latex("x", template=template, resource_dir=template.parent)
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ConversionError, match="outside"):
        md_to_latex("x", template=template, resource_dir=other)
    with pytest.raises(ConversionError, match="not an existing file"):
        md_to_latex("x", template=template.parent / "nope.latex")
    (template.parent / "link.latex").symlink_to("/etc/hostname")
    with pytest.raises(ConversionError, match="outside"):
        md_to_latex("x", template=template.parent / "link.latex", resource_dir=template.parent)


def test_bibliography_and_csl_must_be_inside_resource_dir(tmp_path):
    with pytest.raises(ConversionError, match="outside"):
        md_to_latex(CITES, citations="citeproc", bibliography=BIB / "refs.bib", resource_dir=tmp_path)
    with pytest.raises(ConversionError, match="outside"):
        md_to_latex(CITES, citations="citeproc", csl=BIB / "numeric.csl", resource_dir=tmp_path)


def test_invalid_variable_name(template):
    with pytest.raises(ValueError, match="variable"):
        md_to_latex("x", template=template, variables={"bad name": "v"})


def test_resource_dir_must_be_a_folder(tmp_path):
    with pytest.raises(ConversionError, match="not a folder"):
        md_to_latex("x", resource_dir=tmp_path / "missing")


# --- images ---------------------------------------------------------------------------

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()


def images(*targets: str) -> str:
    return "\n\n".join(f"Text ![alt {i}]({target}) end." for i, target in enumerate(targets))


def test_images_without_resource_dir():
    result = convert_md_to_latex(
        images("fig.png", "sub/fig.png", "/etc/passwd", "../up.png", "C:/x.png", "https://e.org/a.png",
               "file:///etc/passwd", f"data:image/png;base64,{PNG}")
    )
    kept = ["{fig.png}", "{sub/fig.png}"]
    for target in kept:
        assert target in result.text
    for gone in ("/etc/passwd", "up.png", "C:/x.png", "e.org"):
        assert gone not in result.text
    assert [w.message for w in result.warnings] == [
        "/etc/passwd: absolute path",
        "../up.png: path outside the document folder",
        "C:/x.png: absolute path",
        "https://e.org/a.png: remote image (allow_remote_images=False)",
        "file:///etc/passwd: unsupported URL scheme 'file'",
        # data: URIs pass latex2md's check, but pandoc's LaTeX writer cannot embed them.
        f"data:image/png;base64,{PNG}: pandoc cannot write this image to LaTeX",
    ]
    assert all(w.kind == "dropped_image" for w in result.warnings)
    assert "Text alt 2 end." in result.text  # the alt text replaces a dropped image


def test_remote_images_allowed():
    result = convert_md_to_latex(images("https://e.org/a.png"), allow_remote_images=True)
    assert "\\includegraphics" in result.text and "https://e.org/a.png" in result.text
    assert result.warnings == []


def test_images_with_resource_dir(tmp_path):
    root = tmp_path / "res"
    (root / "figs").mkdir(parents=True)
    (root / "figs" / "ok.png").write_bytes(b"png")
    (tmp_path / "secret.png").write_bytes(b"png")
    (root / "link.png").symlink_to(tmp_path / "secret.png")
    result = convert_md_to_latex(
        images("figs/ok.png", str(root / "figs" / "ok.png"), "missing.png", "../secret.png", "link.png"),
        resource_dir=root,
    )
    assert "\\includegraphics{figs/ok.png}" in result.text.replace("[keepaspectratio]", "")
    assert f"{{{root / 'figs' / 'ok.png'}}}" in result.text
    assert [w.message for w in result.warnings] == [
        "missing.png: missing from resource_dir",
        "../secret.png: outside resource_dir",
        "link.png: outside resource_dir",
    ]


def test_dropped_figure_keeps_its_caption():
    result = convert_md_to_latex("![A caption](/abs/fig.png)\n")
    assert result.text == "A caption\n"
    assert "\\begin{figure}" not in result.text


# --- CLI ----------------------------------------------------------------------------------


def test_cli_md_options(tmp_path, template, capsys):
    source = tmp_path / "in.md"
    source.write_text(CITES + "\n\n![x](/abs.png)\n", encoding="utf-8")
    args = ["to-latex", str(source), "--template", str(template), "-V", "class=article", "-V", "recipient=Bob",
            "--citations", "biblatex"]
    assert cli.main(args) == 0
    captured = capsys.readouterr()
    assert "\\documentclass{article}" in captured.out and "To: Bob" in captured.out
    assert "\\autocite{knuth1984,lovelace1843}" in captured.out
    assert "dropped_image: /abs.png: absolute path" in captured.err
    assert cli.main([*args, "--strict"]) == 1
    assert cli.main(["to-latex", str(source), "--citations", "citeproc", "--bibliography", str(BIB / "refs.bib"),
                     "--csl", str(BIB / "numeric.csl"), "-q"]) == 0
    assert "See {[}1, 2{]}" in capsys.readouterr().out

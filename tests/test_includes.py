from pathlib import Path

import pytest
from conftest import FIXTURES, requires_pandoc

from latex2md import latex_file_to_md, latex_to_md
from latex2md.includes import expand_includes

PAPER = FIXTURES / "paper"


def _project(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp_path


def test_input_variants_are_inlined(tmp_path):
    root = _project(
        tmp_path,
        {
            "a.tex": "A",
            "b.tex": "B",
            "sub/c.tex": "C",
            "sub/d.tex": "D \\input{e}",
            "sub/e.tex": "E",
            "listing.py": "print(1)",
        },
    )
    src = "\\input{a} \\input b.tex \\include{sub/c} \\import{sub/}{d} \\lstinputlisting[x=y]{listing.py}"
    out = expand_includes(src, root)
    for expected in ("A", "B", "C", "D", "E", "\\begin{verbatim}\nprint(1)\n\\end{verbatim}"):
        assert expected in out
    assert "\\input" not in out and "\\include" not in out


def test_paths_outside_base_dir_are_never_read(tmp_path):
    secret = tmp_path / "secret.tex"
    secret.write_text("TOP-SECRET", encoding="utf-8")
    root = tmp_path / "project"
    root.mkdir()
    (root / "link.tex").symlink_to(secret)
    src = f"\\input{{{secret}}} \\input{{../secret}} \\input{{link}} \\lstinputlisting{{../secret.tex}}"
    assert "TOP-SECRET" not in expand_includes(src, root)


def test_without_base_dir_includes_are_dropped():
    assert expand_includes("x \\input{a} \\include{b} y", None) == "x   y"


def test_include_cycles_and_commented_includes(tmp_path):
    root = _project(tmp_path, {"a.tex": "A \\input{b}", "b.tex": "B \\input{a}\n% \\input{c}\n", "c.tex": "C"})
    out = expand_includes("\\input{a}", root)
    assert out.count("A") == 1 and out.count("B") == 1
    assert "C" not in out


def test_subfile_keeps_only_document_body(tmp_path):
    root = _project(
        tmp_path,
        {"part.tex": "\\documentclass[main]{subfiles}\n\\begin{document}\nBODY\n\\end{document}\n"},
    )
    out = expand_includes("\\subfile{part}", root)
    assert "BODY" in out and "documentclass" not in out


@requires_pandoc
def test_pandoc_is_sandboxed(tmp_path, monkeypatch):
    """Even if an include slipped past expansion, pandoc must not read it."""
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    from latex2md.pandoc import run_pandoc

    out = run_pandoc("\\input{secret.txt}", from_format="latex", to_format="markdown")
    assert "TOP-SECRET" not in out


@requires_pandoc
def test_latex_to_md_base_dir(tmp_path):
    root = _project(tmp_path, {"intro.tex": "\\section{Intro}\nHello."})
    assert latex_to_md("\\input{intro}", base_dir=root) == "# Intro\n\nHello.\n"
    assert latex_to_md("\\input{intro}") == "\n"


@pytest.fixture(scope="module")
def paper_md() -> str:
    return latex_file_to_md(PAPER / "main.tex")


@requires_pandoc
class TestArxivStylePaper:
    def test_front_matter(self, paper_md):
        assert paper_md.startswith("---\n")
        assert "title: Sparse Attention for Long Reaction Sequences" in paper_md
        assert "- A. Researcher" in paper_md
        assert "such as $\\ce{2H2 + O2 -> 2H2O}$" in paper_md

    def test_sections_from_included_files_in_order(self, paper_md):
        positions = [paper_md.index(h) for h in ("# Introduction", "# Method", "# Results", "# References")]
        assert positions == sorted(positions)
        assert "- A sparse attention layer for $x \\in \\mathbb{R}^d$." in paper_md

    def test_hostile_and_commented_includes_skipped(self, paper_md):
        assert "unused" not in paper_md
        hostname = Path("/etc/hostname")
        if hostname.is_file() and hostname.read_text().strip():
            assert hostname.read_text().strip() not in paper_md

    def test_macros_are_expanded(self, paper_md):
        assert "SparseRx" in paper_md
        assert "\\model" not in paper_md and "\\norm" not in paper_md

    def test_display_math_is_its_own_block_without_labels(self, paper_md):
        assert "The loss combines two terms:\n\n$$\\begin{aligned}" in paper_md
        # 0.3.0: align rows are numbered (1) and (2); the block carries one tag outside
        # aligned (KaTeX cannot tag rows of aligned) and \eqref resolves to the number.
        assert "\\end{aligned} \\tag{1–2}$$\n\nEquation (1) is minimised" in paper_md
        assert "\\label" not in paper_md

    def test_references_are_text_not_dead_links(self, paper_md):
        assert "in Section 3." in paper_md
        assert "Table 1 compares" in paper_md
        assert "](#" not in paper_md

    def test_table_figure_and_listing(self, paper_md):
        assert "**Table 1:** Accuracy on the benchmark.\n\n| Model    | Accuracy | Params |" in paper_md
        assert "| SparseRx | **83.4** |  95M   |" in paper_md
        assert "![Figure 1: Attention pattern of SparseRx.](figures/attention.png)" in paper_md
        assert "```text\ndef score(q, k):\n    return (q @ k.T) / 8  # 100% vectorised\n```" in paper_md

    def test_no_html_or_pandoc_only_syntax(self, paper_md):
        for leak in ("<div", "</div>", ":::", "{#", "\n: "):
            assert leak not in paper_md

    def test_bibliography_and_footnote(self, paper_md):
        assert "# References\n\n- A. Vaswani et al. Attention is all you need. NeurIPS, 2017." in paper_md
        assert "{9}" not in paper_md and "\n9 " not in paper_md
        assert "[^1]: With sequence length $n$." in paper_md

    def test_body_abstract_mode(self):
        md = latex_file_to_md(PAPER / "main.tex", front_matter=False)
        assert md.startswith("# Abstract\n\nWe study SparseRx")
        assert "title:" not in md


@requires_pandoc
def test_bbl_fills_bibliography(tmp_path):
    root = _project(
        tmp_path,
        {
            "paper.tex": "\\begin{document}\nText \\cite{k}.\n\\bibliography{refs}\n\\end{document}\n",
            "paper.bbl": "\\begin{thebibliography}{1}\n\\bibitem{k} Knuth. TeX. 1984.\n\\end{thebibliography}\n",
        },
    )
    md = latex_file_to_md(root / "paper.tex")
    assert "# References\n\n- Knuth. TeX. 1984." in md

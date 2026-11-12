from conftest import requires_pandoc

from latex2md import md_to_latex

pytestmark = requires_pandoc


def test_fragment_structure(sample_md):
    out = md_to_latex(sample_md)
    assert "\\documentclass" not in out
    assert "\\section{Introduction}" in out
    assert "\\subsection{Method}" in out
    assert "\\begin{enumerate}" in out and "\\begin{itemize}" in out
    assert "\\textbf{bold}" in out and "\\emph{italic}" in out
    assert "\\href{https://example.com}{link}" in out
    assert "\\includegraphics{figure.png}" in out


def test_fragment_has_no_template_only_macros(sample_md):
    out = md_to_latex(sample_md)
    for macro in ("\\hypertarget", "\\tightlist", "\\begin{Shaded}", "\\citep"):
        assert macro not in out


def test_math_and_mhchem_preserved(sample_md):
    out = md_to_latex(sample_md)
    assert "\\(\\ce{H2O}\\)" in out
    assert "\\(E = mc^2\\)" in out
    assert "\\int_0^1 x^2 \\, dx = \\frac{1}{3}" in out


def test_citation_becomes_cite(sample_md):
    assert "\\cite{einstein1905}" in md_to_latex(sample_md)


def test_code_block_is_verbatim_and_escapes_nothing(sample_md):
    out = md_to_latex(sample_md)
    assert '\\begin{verbatim}\nprint("50% done")  # not a comment\n\\end{verbatim}' in out


def test_table(sample_md):
    out = md_to_latex(sample_md)
    assert "\\begin{longtable}" in out
    assert "a & 1 \\\\" in out


def test_standalone_document_loads_mhchem(sample_md):
    out = md_to_latex(sample_md, standalone=True)
    assert out.startswith("% Options for packages") or "\\documentclass" in out
    assert "\\usepackage[version=4]{mhchem}\n\\begin{document}" in out
    assert out.rstrip().endswith("\\end{document}")


def test_standalone_without_chemistry_skips_mhchem():
    assert "mhchem" not in md_to_latex("Just text.", standalone=True)


def test_empty_input():
    assert md_to_latex("") == "\n"

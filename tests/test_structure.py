import json
import re
import shutil
import subprocess

import pytest
from conftest import FIXTURES, requires_pandoc

from latex2md import (
    convert_latex_file_to_md,
    convert_latex_to_md,
    latex_file_to_md,
    latex_to_md,
)
from latex2md.algorithms import format_algorithm2e, format_algorithmic

STRUCTURE = FIXTURES / "structure"
pytestmark = requires_pandoc


def md(body: str, **kwargs) -> str:
    return latex_to_md(body, **kwargs)


# --- golden fixture -----------------------------------------------------------


def test_golden_structure_fixture():
    expected = (STRUCTURE / "expected.md").read_text(encoding="utf-8")
    assert latex_file_to_md(STRUCTURE / "main.tex") == expected


def test_golden_structure_fixture_with_anchors():
    expected = (STRUCTURE / "expected_anchors.md").read_text(encoding="utf-8")
    assert latex_file_to_md(STRUCTURE / "main.tex", anchors=True) == expected


def test_fixture_warnings():
    result = convert_latex_file_to_md(STRUCTURE / "main.tex")
    assert [(w.kind, w.message) for w in result.warnings] == [
        ("unresolved_reference", "\\ref{nope}: no such \\label"),
        ("unknown_environment", "\\begin{mystery}"),
    ]


def test_output_is_plain_markdown():
    out = latex_file_to_md(STRUCTURE / "main.tex", anchors=True)
    for leak in ("<span", "<div", ":::", "{#", "\\label", "\\begin{equation", "\\begin{align}", "\\nonumber"):
        assert leak not in out


# --- equations ------------------------------------------------------------------


def test_equation_numbering_and_refs():
    out = md(
        "\\begin{equation}a\\label{x}\\end{equation}"
        "\\begin{equation*}b\\end{equation*}"
        "\\[c\\]"
        "\\begin{equation}d\\nonumber\\end{equation}"
        "\\begin{equation}e\\label{y}\\end{equation}"
        "See \\eqref{x}, \\ref{y} and \\cref{x,y}."
    )
    assert "$$a \\tag{1}$$" in out
    assert "$$b$$" in out and "$$c$$" in out and "$$d$$" in out
    assert "$$e \\tag{2}$$" in out
    assert "See (1), (2) and Equations (1) and (2)." in out


def test_align_rows_are_counted_and_tagged_once_outside_aligned():
    out = md(
        "\\begin{align} a&=1 \\label{r1}\\\\ b&=2 \\notag \\\\ c&=3 \\label{r3} \\end{align}"
        "\\begin{equation}z\\end{equation} See \\eqref{r1} \\eqref{r3}"
    )
    assert "\\end{aligned} \\tag{1–2}$$" in out
    assert "$$z \\tag{3}$$" in out
    assert "See (1) (2)" in out
    # KaTeX cannot tag rows of aligned: no \tag inside it.
    for block in re.findall(r"\\begin\{aligned\}.*?\\end\{aligned\}", out, re.DOTALL):
        assert "\\tag" not in block


def test_single_numbered_align_row_and_user_tags():
    out = md("\\begin{align} a&=1 \\nonumber\\\\ b&=2 \\end{align}\\begin{equation}x\\tag{A}\\label{t}\\end{equation}See \\ref{t}")
    assert "\\end{aligned} \\tag{1}$$" in out
    assert "$$x \\tag{A}$$" in out and "See (A)" in out


def test_gather_multline_alignat_environments():
    out = md(
        "\\begin{gather} a \\\\ b \\end{gather}"
        "\\begin{multline} a \\\\ b \\end{multline}"
        "\\begin{alignat}{2} a &= b & c &= d \\end{alignat}"
        "\\begin{eqnarray} a &=& b \\end{eqnarray}"
    )
    assert "\\begin{gathered}\na \\\\ b\n\\end{gathered} \\tag{1–2}$$" in out
    assert "\\begin{gathered}\na \\\\ b\n\\end{gathered} \\tag{3}$$" in out
    assert "\\begin{alignedat}{2}\na &= b & c &= d\n\\end{alignedat} \\tag{4}$$" in out
    assert "\\begin{aligned}\na &=& b\n\\end{aligned} \\tag{5}$$" in out


def test_equations_numbered_within_sections_and_chapters():
    out = md(
        "\\numberwithin{equation}{section}\\begin{document}\\section{A}\\begin{equation}x\\end{equation}"
        "\\section{B}\\begin{equation}y\\end{equation}\\end{document}"
    )
    assert "\\tag{1.1}" in out and "\\tag{2.1}" in out
    book = md(
        "\\documentclass{book}\\begin{document}\\chapter{One}\\section{S}\\label{s}"
        "\\begin{figure}\\includegraphics{a.png}\\caption{C}\\label{f}\\end{figure}"
        "\\begin{equation}x\\end{equation}\\ref{s} \\ref{f}\\end{document}"
    )
    assert "\\tag{1.1}" in book and "![Figure 1.1: C](a.png)" in book and "1.1 1.1" in book


def test_label_never_left_in_math():
    out = md("$$a \\label{q}$$ \\[b\\label{r}\\] \\begin{align*}c\\label{s}\\end{align*}")
    assert "\\label" not in out


def test_katex_renders_tagged_output():
    """Optional: render every display equation of the fixture with KaTeX."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    probe = subprocess.run([node, "-e", "require('katex')"], capture_output=True, check=False)
    if probe.returncode != 0:
        pytest.skip("katex not installed for node (npm install katex, set NODE_PATH)")
    out = latex_file_to_md(STRUCTURE / "main.tex")
    script = (
        "const k=require('katex');let fail=0;"
        "for (const m of JSON.parse(require('fs').readFileSync(0,'utf8'))){"
        "try{k.renderToString(m,{displayMode:true,throwOnError:true})}catch(e){fail=1;console.log(m,e.message)}}"
        "process.exit(fail)"
    )
    maths = re.findall(r"\$\$(.*?)\$\$", out, re.DOTALL)
    run = subprocess.run([node, "-e", script], input=json.dumps(maths), text=True, capture_output=True, check=False)
    assert run.returncode == 0, run.stdout


# --- sections, figures, tables ----------------------------------------------------


def test_section_numbers_and_appendix():
    out = md(
        "\\begin{document}\\section{A}\\subsection{B}\\label{b}\\section*{Unnumbered}\\section{C}\\label{c}"
        "\\appendix\\section{D}\\label{d}\\subsection{E}\\label{e}"
        "\\ref{b} \\ref{c} \\ref{d} \\ref{e} \\autoref{e} \\Cref{c}\\end{document}"
    )
    assert "1.1 2 A A.1 Appendix A.1 Section 2" in out


def test_figure_and_table_numbers_with_captionof_and_subfloat():
    out = md(
        "\\begin{figure}\\includegraphics{a.png}\\caption{First}\\label{f1}\\end{figure}"
        "\\begin{table}\\begin{tabular}{l}x\\\\\\end{tabular}\\caption{Tab}\\label{t1}\\end{table}"
        "\\begin{figure}\\subfloat[Left\\label{l}]{\\includegraphics{l.png}}"
        "\\subfloat[Right]{\\includegraphics{r.png}}\\caption{Second}\\label{f2}\\end{figure}"
        "\\begin{minipage}{x}\\includegraphics{m.png}\\captionof{figure}{Third}\\label{f3}\\end{minipage}"
        "Refs \\ref{f1} \\ref{t1} \\ref{f2} \\ref{l} \\subref{l} \\ref{f3}."
    )
    assert "![Figure 1: First](a.png)" in out
    assert "**Table 1:** Tab" in out
    assert "![(a) Left](l.png)\n\n![(b) Right](r.png)\n\n**Figure 2:** Second" in out
    assert "**Figure 3:** Third" in out
    assert "Refs 1 1 2 2a (a) 3." in out


def test_unnumbered_table_caption_keeps_old_label():
    assert md("\\begin{table}\\caption*{Plain}\\begin{tabular}{l}x\\\\\\end{tabular}\\end{table}").startswith(
        "**Table:** Plain"
    )


def test_enumerate_item_refs():
    out = md(
        "\\begin{enumerate}\\item a\\label{i1}\\item b\\begin{enumerate}\\item c\\label{i2}\\end{enumerate}"
        "\\end{enumerate}\\ref{i1} \\ref{i2}"
    )
    assert out.rstrip().endswith("1 2a")


def test_unresolved_reference_warns_and_keeps_label_text():
    result = convert_latex_to_md("See \\cref{x_y} and \\eqref{z}.")
    assert result.text == "See (x_y) and (z).\n"
    assert [w.kind for w in result.warnings] == ["unresolved_reference", "unresolved_reference"]


def test_refs_in_verbatim_are_untouched():
    out = md("\\section{A}\\label{a}\\begin{verbatim}\\ref{a}\\end{verbatim} \\verb|\\ref{a}| \\ref{a}")
    assert "\\ref{a}" in out and out.rstrip().endswith("1")


def test_anchors_link_only_section_numbers():
    out = md("\\section{Intro}\\label{i}\\section{Intro}\\label{j}\\begin{equation}x\\label{e}\\end{equation}"
             "\\ref{i} \\ref{j} \\eqref{e} \\hyperref[j]{this}", anchors=True)
    assert "[1](#intro) [2](#intro-1) (1) [this](#intro-1)" in out
    assert "<a" not in out and "{#" not in out


# --- theorems and proofs ------------------------------------------------------------


def test_theorem_counters_shared_within_and_starred():
    out = md(
        "\\newtheorem{thm}{Theorem}[section]\\newtheorem{lem}[thm]{Lemma}\\newtheorem*{rem}{Remark}"
        "\\newtheorem{conj}{Conjecture}"
        "\\begin{document}\\section{S}"
        "\\begin{thm}A\\end{thm}\\begin{lem}[Key]\\label{k}B\\end{lem}\\begin{rem}C\\end{rem}"
        "\\begin{conj}D\\end{conj}\\section{T}\\begin{thm}E\\end{thm}\\cref{k}\\end{document}"
    )
    assert "**Theorem 1.1.** A" in out
    assert "**Lemma 1.2 (Key).** B" in out
    assert "**Remark.** C" in out
    assert "**Conjecture 1.** D" in out
    assert "**Theorem 2.1.** E" in out
    assert "Lemma 1.2" in out.splitlines()[-1]


def test_undeclared_amsthm_names_and_declaretheorem():
    out = md(
        "\\declaretheorem[name=Claim, numberwithin=section]{clm}"
        "\\begin{document}\\section{S}\\begin{lemma}L\\end{lemma}\\begin{example}E\\end{example}"
        "\\begin{clm}C\\end{clm}\\end{document}"
    )
    assert "**Lemma 1.** L" in out and "**Example 1.** E" in out and "**Claim 1.1.** C" in out


def test_proof_with_title_and_qed():
    out = md("\\begin{proof}[Proof of Theorem 1]Easy.\\end{proof}")
    assert out == "*Proof of Theorem 1.* Easy. ∎\n"


def test_unknown_environment_keeps_content_and_warns():
    result = convert_latex_to_md("\\begin{document}\n\\begin{boxed}Kept text.\\end{boxed}\n\\end{document}")
    assert "Kept text." in result.text
    assert [w.message for w in result.warnings] == ["\\begin{boxed}"]


# --- algorithms --------------------------------------------------------------------


def test_algorithm2e_block():
    out = md(
        "\\begin{algorithm}\\SetAlgoLined\\KwIn{graph $G$}\\KwOut{order}"
        "$S \\gets \\emptyset$\\;\\While{$Q \\neq \\emptyset$}{\\eIf{$x$}{a\\;}{b\\; \\tcp{note}}}"
        "\\caption{Topological sort}\\label{alg:topo}\\end{algorithm} See \\cref{alg:topo}."
    )
    assert out.startswith("**Algorithm 1:** Topological sort\n\n```text\n")
    assert (
        "Input: graph $G$\nOutput: order\n$S \\gets \\emptyset$\nwhile $Q \\neq \\emptyset$ do\n"
        "    if $x$ then\n        a\n    else\n        b\n        // note\n    end\nend\n```"
    ) in out
    assert "See Algorithm 1." in out


def test_old_algorithmic_without_algorithm_float():
    out = md("\\begin{algorithmic}\\STATE $x \\leftarrow 0$\\IF{$x$}\\RETURN $x$\\ENDIF\\end{algorithmic}")
    assert out == "```text\n$x \\leftarrow 0$\nif $x$ then\n    return $x$\nend if\n```\n"


def test_algorithmic_formatter_line_labels():
    labels = []
    text = format_algorithmic(
        "\\State a\\State b\\label{l}\\While{c}\\State d\\EndWhile",
        numbered=True,
        on_label=lambda label, line: labels.append((label, line)),
    )
    assert text == "1: a\n2: b\n3: while c do\n4:     d\n5: end while"
    assert labels == [("l", "2")]


def test_algorithm2e_formatter_line_constructs():
    text = format_algorithm2e("\\uIf{a}{x\\;}\\uElseIf{b}{y\\;}\\Else{z\\;}\\lForEach{$i$}{w}\\Repeat{done}{s\\;}")
    assert text == (
        "if a then\n    x\nelse if b then\n    y\nelse\n    z\nend\nforeach $i$ do w\nrepeat\n    s\nuntil done"
    )

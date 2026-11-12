from conftest import requires_pandoc

from latex2md import latex_to_md
from latex2md.comments import strip_comments

pytestmark = requires_pandoc


def test_document_structure(sample_tex):
    out = latex_to_md(sample_tex)
    assert out.startswith("# Introduction\n")
    assert "\n## Method\n" in out
    assert "**bold**" in out and "*italic*" in out
    assert "[link](https://example.com)" in out


def test_no_pandoc_only_syntax(sample_tex):
    out = latex_to_md(sample_tex)
    assert "{#" not in out
    assert ":::" not in out
    assert "{.unnumbered}" not in out


def test_math_and_citations(sample_tex):
    out = latex_to_md(sample_tex)
    assert "$\\ce{H2O}$" in out
    assert "$E = mc^2$" in out
    # 0.3.0: a numbered equation environment carries its number as \tag.
    assert "$$\\int_0^1 x^2 \\, dx = \\frac{1}{3} \\tag{1}$$" in out
    assert "[@einstein1905]" in out


def test_lists_are_tight_with_single_space_markers(sample_tex):
    out = latex_to_md(sample_tex)
    assert "1. First step\n2. Second step" in out
    assert "- Bullet with `inline code`\n- Bullet with a [link]" in out


def test_tabular_becomes_pipe_table_with_header(sample_tex):
    out = latex_to_md(sample_tex)
    assert "| Name | Value |\n|:-----|------:|\n| a    |     1 |" in out


def test_comments_removed_but_escaped_percent_and_verbatim_kept(sample_tex):
    out = latex_to_md(sample_tex)
    assert "comment" not in out.replace("# keep me", "")
    assert "50% accuracy" in out
    assert '```text\nprint("50% done")  # keep me\n```' in out


def test_fragment_input():
    assert latex_to_md("Hello \\textbf{world} and $x^2$.") == "Hello **world** and $x^2$.\n"


def test_strip_comments_keeps_verb():
    src = "a \\verb|50%| b % gone\n% whole line\nc 10\\% d\n"
    assert strip_comments(src) == "a \\verb|50%| b \nc 10\\% d\n"

from conftest import requires_pandoc

from latex2md import latex_to_md, md_to_latex

pytestmark = requires_pandoc


def test_markdown_roundtrip_is_stable(sample_md):
    once = latex_to_md(md_to_latex(sample_md))
    twice = latex_to_md(md_to_latex(once))
    assert once == twice


def test_markdown_roundtrip_keeps_content(sample_md):
    out = latex_to_md(md_to_latex(sample_md))
    for expected in (
        "# Introduction",
        "## Method",
        "$\\ce{H2O}$",
        "[@einstein1905]",
        "1. First step",
        "- Bullet with `inline code`",
        "$$\\int_0^1 x^2 \\, dx = \\frac{1}{3}$$",
        "| Name | Value |",
        'print("50% done")  # not a comment',
    ):
        assert expected in out


def test_latex_roundtrip_is_stable(sample_tex):
    once = md_to_latex(latex_to_md(sample_tex))
    twice = md_to_latex(latex_to_md(once))
    assert once == twice

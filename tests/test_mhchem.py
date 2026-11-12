import pytest

from latex2md.mhchem import wrap_text_mode_mhchem


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (r"water is \ce{H2O}.", r"water is $\ce{H2O}$."),
        (r"\cf{CO2}", r"$\cf{CO2}$"),
        (r"\ce{A^{2+}_{(aq)}}", r"$\ce{A^{2+}_{(aq)}}$"),
        (r"$x \ce{H2O}$", r"$x \ce{H2O}$"),
        (r"$$\ce{Q}$$ \ce{R}", r"$$\ce{Q}$$ $\ce{R}$"),
        (r"\(\ce{X}\) \[\ce{Y}\]", r"\(\ce{X}\) \[\ce{Y}\]"),
        (r"\begin{align*}\ce{Y}\end{align*} \ce{Z}", r"\begin{align*}\ce{Y}\end{align*} $\ce{Z}$"),
        (r"costs \$5 for \ce{NaCl}", r"costs \$5 for $\ce{NaCl}$"),
        (r"\ce{unbalanced", r"\ce{unbalanced"),
        ("no chemistry", "no chemistry"),
    ],
)
def test_wrap_text_mode_mhchem(source, expected):
    assert wrap_text_mode_mhchem(source) == expected

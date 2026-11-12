"""Markdown <-> LaTeX conversion built on pandoc."""
from latex2md.latex_to_md import (
    convert_latex_file_to_md,
    convert_latex_to_md,
    latex_file_to_md,
    latex_to_md,
)
from latex2md.md_to_latex import convert_md_to_latex, md_to_latex
from latex2md.pandoc import ConversionError, pandoc_available
from latex2md.result import ConversionResult, ConversionWarning

__all__ = [
    "ConversionError",
    "ConversionResult",
    "ConversionWarning",
    "convert_latex_file_to_md",
    "convert_latex_to_md",
    "convert_md_to_latex",
    "latex_file_to_md",
    "latex_to_md",
    "md_to_latex",
    "pandoc_available",
]
__version__ = "0.2.0"

"""Markdown <-> LaTeX conversion built on pandoc."""
from latex2md.archive import ArchiveError, ArchiveLimits, open_latex_archive
from latex2md.flatten import flatten_latex
from latex2md.latex_to_md import (
    convert_latex_archive_to_md,
    convert_latex_file_to_md,
    convert_latex_to_md,
    latex_archive_to_md,
    latex_file_to_md,
    latex_to_md,
)
from latex2md.md_to_latex import convert_md_to_latex, md_to_latex
from latex2md.pandoc import ConversionError, pandoc_available
from latex2md.result import ConversionResult, ConversionWarning

__all__ = [
    "ArchiveError",
    "ArchiveLimits",
    "ConversionError",
    "ConversionResult",
    "ConversionWarning",
    "convert_latex_archive_to_md",
    "convert_latex_file_to_md",
    "convert_latex_to_md",
    "convert_md_to_latex",
    "flatten_latex",
    "latex_archive_to_md",
    "latex_file_to_md",
    "latex_to_md",
    "md_to_latex",
    "open_latex_archive",
    "pandoc_available",
]
__version__ = "0.2.0"

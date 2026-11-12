"""Command-line interface: ``latex2md to-latex|to-md|auto``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from latex2md.latex_to_md import latex_to_md
from latex2md.md_to_latex import md_to_latex
from latex2md.pandoc import ConversionError

MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown"}
LATEX_SUFFIXES = {".tex", ".latex", ".ltx"}


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _write(path: str | None, text: str) -> None:
    if not path or path == "-":
        sys.stdout.write(text)
    else:
        Path(path).write_text(text, encoding="utf-8")


def _direction(command: str, path: str) -> str:
    if command != "auto":
        return command
    suffix = Path(path).suffix.lower()
    if suffix in MARKDOWN_SUFFIXES:
        return "to-latex"
    if suffix in LATEX_SUFFIXES:
        return "to-md"
    raise ConversionError(f"cannot tell the input format from {path!r}; use to-latex or to-md")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="latex2md", description="Convert between Markdown and LaTeX.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("to-latex", "Markdown -> LaTeX"),
        ("to-md", "LaTeX -> Markdown"),
        ("auto", "pick the direction from the input file extension"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("input", nargs="?", default="-", help="input file, or - for stdin (default)")
        cmd.add_argument("-o", "--output", help="output file (default: stdout)")
        if name != "to-md":
            cmd.add_argument("--standalone", action="store_true", help="emit a complete LaTeX document")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        direction = _direction(args.command, args.input)
        source = _read(args.input)
        if direction == "to-latex":
            result = md_to_latex(source, standalone=getattr(args, "standalone", False))
        else:
            result = latex_to_md(source)
        _write(args.output, result)
    except (ConversionError, OSError) as exc:
        print(f"latex2md: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

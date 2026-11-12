"""Command-line interface: ``latex2md to-latex|to-md|auto``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from latex2md.latex_to_md import convert_latex_file_to_md, convert_latex_to_md
from latex2md.md_to_latex import convert_md_to_latex
from latex2md.pandoc import ConversionError
from latex2md.result import ConversionResult

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
        if name != "to-latex":
            cmd.add_argument(
                "--base-dir",
                help="folder that \\input/\\include may read from (default: the input file's folder, or cwd for stdin)",
            )
        if name != "to-md":
            cmd.add_argument("--standalone", action="store_true", help="emit a complete LaTeX document")
        cmd.add_argument("--strict", action="store_true", help="exit with status 1 if there are any warnings")
        cmd.add_argument("-q", "--quiet", action="store_true", help="do not print warnings")
    return parser


def _report(result: ConversionResult, args: argparse.Namespace) -> int:
    if not args.quiet:
        for warning in result.warnings:
            print(f"latex2md: warning: {warning}", file=sys.stderr)
    return 1 if args.strict and result.warnings else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        direction = _direction(args.command, args.input)
        if direction == "to-latex":
            result = convert_md_to_latex(_read(args.input), standalone=getattr(args, "standalone", False))
        elif args.input == "-":
            result = convert_latex_to_md(_read(args.input), base_dir=args.base_dir or Path.cwd())
        else:
            result = convert_latex_file_to_md(args.input, base_dir=args.base_dir)
        _write(args.output, result.text)
    except (ConversionError, OSError) as exc:
        print(f"latex2md: {exc}", file=sys.stderr)
        return 1
    return _report(result, args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

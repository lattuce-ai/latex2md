"""Command-line interface: ``latex2md to-latex|to-md|auto|flatten``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from latex2md.archive import extract_archive
from latex2md.flatten import flatten_source, read_tex, sibling_bbl
from latex2md.latex_to_md import (
    convert_latex_archive_to_md,
    convert_latex_file_to_md,
    convert_latex_to_md,
)
from latex2md.md_to_latex import convert_md_to_latex
from latex2md.pandoc import ConversionError
from latex2md.result import ConversionResult, WarningLog

MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown"}
LATEX_SUFFIXES = {".tex", ".latex", ".ltx"}
ARCHIVE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz", ".gz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")


def _is_archive(path: str) -> bool:
    return path != "-" and path.lower().endswith(ARCHIVE_SUFFIXES)


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
    if suffix in LATEX_SUFFIXES or _is_archive(path):
        return "to-md"
    raise ConversionError(f"cannot tell the input format from {path!r}; use to-latex or to-md")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="latex2md", description="Convert between Markdown and LaTeX.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("to-latex", "Markdown -> LaTeX"),
        ("to-md", "LaTeX -> Markdown"),
        ("auto", "pick the direction from the input file extension"),
        ("flatten", "LaTeX -> one LaTeX file with includes inlined and comments removed"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument(
            "input",
            nargs="?",
            default="-",
            help="input file (.zip/.tar/.tar.gz/.tgz archives too, except for to-latex), or - for stdin (default)",
        )
        cmd.add_argument("-o", "--output", help="output file (default: stdout)")
        if name != "to-latex":
            cmd.add_argument(
                "--base-dir",
                help="folder that \\input/\\include may read from (default: the input file's folder, or cwd for stdin)",
            )
        if name in ("to-md", "auto"):
            cmd.add_argument("--anchors", action="store_true", help="link section references to heading ids")
            cmd.add_argument("--csl", help="CSL style: for to-md, references from a .bib (inside --base-dir); "
                             "for to-latex, --citations citeproc")
            cmd.add_argument(
                "--cite-style",
                choices=("keep", "rendered"),
                default="keep",
                help="keep [@key] (default) or write citeproc's rendered citations",
            )
        if name in ("to-latex", "auto"):
            cmd.add_argument("--standalone", action="store_true", help="emit a complete LaTeX document")
            cmd.add_argument("--template", help="pandoc LaTeX template (implies --standalone)")
            cmd.add_argument(
                "-V",
                "--variable",
                action="append",
                default=[],
                metavar="KEY=VALUE",
                help="template variable; repeat for more",
            )
            cmd.add_argument("--bibliography", help=".bib or CSL JSON file for citations")
            cmd.add_argument(
                "--citations",
                choices=("cite", "natbib", "biblatex", "citeproc"),
                default="cite",
                help="how [@key] is written (default: cite)",
            )
            cmd.add_argument("--resource-dir", help="folder images must be inside")
            cmd.add_argument(
                "--allow-remote-images", action="store_true", help="keep http(s) images instead of dropping them"
            )
            if name == "to-latex":
                cmd.add_argument("--csl", help="CSL style for --citations citeproc")
        cmd.add_argument("--strict", action="store_true", help="exit with status 1 if there are any warnings")
        cmd.add_argument("-q", "--quiet", action="store_true", help="do not print warnings")
    return parser


def _report(result: ConversionResult, args: argparse.Namespace) -> int:
    if not args.quiet:
        for warning in result.warnings:
            print(f"latex2md: warning: {warning}", file=sys.stderr)
    return 1 if args.strict and result.warnings else 0


def _latex_options(args: argparse.Namespace) -> dict:
    variables = {}
    for item in args.variable:
        key, sep, value = item.partition("=")
        if not sep:
            key, sep, value = item.partition(":")
        variables[key] = value
    return {
        "standalone": args.standalone,
        "template": args.template,
        "variables": variables,
        "bibliography": args.bibliography,
        "citations": args.citations,
        "csl": args.csl,
        "resource_dir": args.resource_dir,
        "allow_remote_images": args.allow_remote_images,
    }


def _flatten(args: argparse.Namespace) -> ConversionResult:
    warnings = WarningLog()
    if _is_archive(args.input):
        with extract_archive(Path(args.input).read_bytes()) as archive:
            main_tex = archive.main_tex
            text = flatten_source(read_tex(main_tex), base_dir=archive.root, bbl=sibling_bbl(main_tex), warnings=warnings)
        for message in archive.skipped:
            warnings.add("skipped_member", message)
    elif args.input == "-":
        text = flatten_source(_read("-"), base_dir=args.base_dir or Path.cwd(), bbl=None, warnings=warnings)
    else:
        path = Path(args.input)
        text = flatten_source(read_tex(path), base_dir=args.base_dir or path.parent, bbl=sibling_bbl(path), warnings=warnings)
    return ConversionResult(text, list(warnings))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "flatten":
            result = _flatten(args)
            _write(args.output, result.text)
            return _report(result, args)
        direction = _direction(args.command, args.input)
        if direction == "to-latex":
            result = convert_md_to_latex(_read(args.input), **_latex_options(args))
        else:
            options = {"anchors": args.anchors, "cite_style": args.cite_style}
            if _is_archive(args.input):
                result = convert_latex_archive_to_md(Path(args.input).read_bytes(), **options)
            elif args.input == "-":
                base_dir = args.base_dir or Path.cwd()
                result = convert_latex_to_md(_read(args.input), base_dir=base_dir, csl=args.csl, **options)
            else:
                result = convert_latex_file_to_md(args.input, base_dir=args.base_dir, csl=args.csl, **options)
        _write(args.output, result.text)
    except (ConversionError, OSError, ValueError) as exc:
        print(f"latex2md: {exc}", file=sys.stderr)
        return 1
    return _report(result, args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

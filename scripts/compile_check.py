#!/usr/bin/env python3
"""Compile latex2md's LaTeX output with a real TeX engine.

Unit tests compare strings; only a TeX run proves the output compiles. This
converts the Markdown fixtures and a few LaTeX -> Markdown -> LaTeX round
trips to standalone documents, plus the Markdown fixture as a fragment in an
ordinary preamble (latex2md promises fragments need no pandoc-only macros),
and runs ``latexmk -pdf -interaction=nonstopmode`` on each. Any failure
makes the script exit 1. CI runs it in the ``compile`` job; it needs TeX Live
(texlive-latex-recommended, texlive-latex-extra, texlive-science, lmodern, latexmk).

    python scripts/compile_check.py [--keep DIR]
"""
from __future__ import annotations

import argparse
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from latex2md import latex_file_to_md, latex_to_md, md_to_latex

FIXTURES = ROOT / "tests" / "fixtures"


def tiny_png() -> bytes:
    """A valid 1x1 grey PNG, written wherever a document includes a missing image."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)  # 1x1, 8-bit greyscale
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"\x00\x80")) + chunk(b"IEND", b"")


FRAGMENT_PREAMBLE = r"""\documentclass{article}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{longtable,booktabs,array,calc}
\usepackage[version=4]{mhchem}
\usepackage{natbib}
\usepackage{hyperref}
\begin{document}
"""
_GRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^{}]+)\}")


def documents() -> dict[str, Callable[[], str]]:
    sample_md = (FIXTURES / "sample.md").read_text(encoding="utf-8")
    sample_tex = (FIXTURES / "sample.tex").read_text(encoding="utf-8")
    docs: dict[str, Callable[[], str]] = {}
    for path in sorted(FIXTURES.glob("*.md")):
        docs[f"md-{path.stem}"] = lambda path=path: md_to_latex(path.read_text(encoding="utf-8"), standalone=True)
    docs["fragment-sample"] = lambda: FRAGMENT_PREAMBLE + md_to_latex(sample_md) + "\n\\end{document}\n"
    docs["roundtrip-sample-tex"] = lambda: md_to_latex(latex_to_md(sample_tex), standalone=True)
    docs["roundtrip-paper"] = lambda: md_to_latex(latex_file_to_md(FIXTURES / "paper" / "main.tex"), standalone=True)
    docs["roundtrip-structure"] = lambda: md_to_latex(
        latex_file_to_md(FIXTURES / "structure" / "main.tex"), standalone=True
    )
    docs["citeproc-standalone"] = lambda: md_to_latex(
        "See [@knuth1984] and @lovelace1843.",
        standalone=True,
        citations="citeproc",
        bibliography=FIXTURES / "bib" / "refs.bib",
    )
    return docs


def compile_one(name: str, latex: str, folder: Path) -> tuple[bool, str]:
    folder.mkdir(parents=True, exist_ok=True)
    for target in _GRAPHICS_RE.findall(latex):
        image = folder / target
        if not target.startswith(("/", "http")) and ".." not in target and not image.exists():
            image.parent.mkdir(parents=True, exist_ok=True)
            image.write_bytes(tiny_png())
    tex = folder / f"{name}.tex"
    tex.write_text(latex, encoding="utf-8")
    command = ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", tex.name]
    try:
        run = subprocess.run(command, cwd=folder, capture_output=True, text=True, timeout=300, check=False)
    except subprocess.TimeoutExpired:
        return False, "latexmk timed out"
    if run.returncode != 0 or not (folder / f"{name}.pdf").is_file():
        log = folder / f"{name}.log"
        tail = log.read_text(encoding="utf-8", errors="replace")[-3000:] if log.is_file() else run.stdout[-3000:]
        return False, tail
    return True, ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", type=Path, help="write the .tex/.pdf files here instead of a temporary folder")
    args = parser.parse_args(argv)
    if not shutil.which("latexmk"):
        print("compile_check: latexmk not found; install TeX Live (see the script docstring)", file=sys.stderr)
        return 2
    failures = 0
    with tempfile.TemporaryDirectory(prefix="latex2md-compile-") as tmp:
        base = args.keep or Path(tmp)
        for name, build in documents().items():
            ok, detail = compile_one(name, build(), base / name)
            print(f"{'ok  ' if ok else 'FAIL'} {name}")
            if not ok:
                failures += 1
                print(detail, file=sys.stderr)
    print(f"{failures} of {len(documents())} documents failed to compile" if failures else "all documents compiled")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

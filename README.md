# latex2md

Convert **Markdown → LaTeX** and **LaTeX → Markdown**, as a Python library or a CLI.

It runs [pandoc](https://pandoc.org) and cleans up the output on both sides, so you get
plain, readable Markdown and LaTeX fragments you can paste into an existing document.

## Install

You need **pandoc** (2.19 or later; tested with 3.1) on your `PATH`:

```bash
sudo apt-get install pandoc
```

```bash
pip install -e .
```

If pandoc is somewhere else, set `LATEX2MD_PANDOC=/path/to/pandoc`.

## CLI

```bash
latex2md to-latex notes.md -o notes.tex
```

```bash
latex2md to-md paper.tex -o paper.md
```

```bash
latex2md auto paper.tex
```

- With no input file, or `-`, it reads stdin. With no `-o`, it writes to stdout.
- `auto` picks the direction from the extension (`.md/.markdown` or `.tex/.latex/.ltx`).
- `--standalone` (for `to-latex` and `auto`) writes a complete document with a preamble.

## Python

```python
from latex2md import md_to_latex, latex_to_md, ConversionError

tex = md_to_latex("# Title\n\nEnergy is $E = mc^2$ [@einstein1905].")
md = latex_to_md(r"\section{Title} Energy is $E = mc^2$ \cite{einstein1905}.")
full = md_to_latex(markdown_text, standalone=True)
```

All errors (pandoc missing, failing or timing out) raise `ConversionError`; its
`.stderr` holds pandoc's message.

## What it handles

| | Markdown → LaTeX | LaTeX → Markdown |
|---|---|---|
| Headings | `\section{}` + `\label{}` | `#`, `##`, … (labels dropped) |
| Math | `\( \)` and `\[ \]` | `$…$` and `$$…$$` |
| Chemistry (`\ce{}`) | kept; `--standalone` loads `mhchem` | kept inside math |
| Citations | `[@key]` → `\cite{key}` | `\cite{key}` → `[@key]` |
| Lists | `itemize` / `enumerate` | tight `-` / `1.` lists |
| Tables | `longtable` (needs `longtable` + `booktabs`) | pipe tables; first row becomes header |
| Code | `verbatim` | fenced blocks |
| Comments | — | `%` comments removed; `\%`, `\verb` and verbatim kept |

Fragment output (the default) avoids macros that only pandoc's template defines
(`\tightlist`, `Shaded`, `\hypertarget`), so it compiles in an ordinary preamble.

## Limitations

- Custom macros and unusual packages in LaTeX are only as good as pandoc's LaTeX reader;
  unknown commands are dropped.
- Cross-references (`\ref{}`) come out as plain text in Markdown.
- Figures with `\includegraphics` keep the path; image files are not copied.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `LATEX2MD_PANDOC` | `pandoc` on `PATH` | pandoc binary to run |
| `LATEX2MD_TIMEOUT` | `60` | seconds before a conversion is stopped |

## Development

```bash
pip install -e '.[dev]'
```

```bash
pytest
```

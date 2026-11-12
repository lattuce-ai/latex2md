# latex2md

Convert **Markdown → LaTeX** and **LaTeX → Markdown**, as a Python library or a CLI.

It runs [pandoc](https://pandoc.org) and cleans up the output on both sides, so you get
plain, readable Markdown and LaTeX fragments you can paste into an existing document.

## Install

You need **pandoc** 3.0 or later (CI tests 3.1 and 3.6) on your `PATH`:

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
- `--base-dir DIR` (for `to-md` and `auto`) is the folder `\input`/`\include` may read from.
  It defaults to the input file's folder (or the current folder for stdin).

## Python

```python
from latex2md import md_to_latex, latex_to_md, ConversionError

tex = md_to_latex("# Title\n\nEnergy is $E = mc^2$ [@einstein1905].")
md = latex_to_md(r"\section{Title} Energy is $E = mc^2$ \cite{einstein1905}.")
full = md_to_latex(markdown_text, standalone=True)

# Multi-file projects (e.g. an unpacked arXiv source archive):
md = latex_file_to_md("paper/main.tex")                      # YAML front matter
md = latex_file_to_md("paper/main.tex", front_matter=False)  # abstract as a section
md = latex_to_md(tex_text, base_dir="paper/")                # text + project folder
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
| Multi-file projects | — | `\input`, `\include`, `\subfile`, `\import`, `\lstinputlisting` inlined from the project folder |
| Title, authors, abstract | — | YAML front matter, or an "Abstract" section with `front_matter=False` |
| Macros (`\newcommand`) | — | expanded |
| Floats | — | `figure` → image with caption as alt text; `table` → "**Table:** caption" + pipe table |
| Cross-references | — | `\ref` → its number as text (no dead `#anchor` links); `\eqref` → `(label)` |
| Bibliography | — | `thebibliography` → "References" list; a sibling `.bbl` fills `\bibliography{}` |

Fragment output (the default) avoids macros that only pandoc's template defines
(`\tightlist`, `Shaded`, `\hypertarget`), so it compiles in an ordinary preamble.

## Safety

LaTeX can name any file on disk (`\input{/etc/passwd}`), so latex2md never lets
pandoc read files itself: pandoc always runs with `--sandbox`, and latex2md
inlines includes only when they resolve inside the base folder. Absolute paths,
`..` escapes, symlinks pointing outside, cycles, nesting deeper than 16 levels and
more than 20 MB of included files are skipped. Without a base folder, include
commands are removed. This makes it safe to run on untrusted uploads.

## Limitations

- Custom macros and unusual packages in LaTeX are only as good as pandoc's LaTeX reader;
  unknown commands are dropped.
- Equations are not numbered in Markdown, so `\eqref` shows the label, e.g. `(eq:loss)`.
- Bibliographies from `.bib` files need the compiled `.bbl`; citations stay as `[@key]`.
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

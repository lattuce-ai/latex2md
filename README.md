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
pip install lattuce-latex2md
```

It supports Python 3.11 to 3.14 and has no Python dependencies.

The distribution is called `lattuce-latex2md` (the name `latex2md` is taken on PyPI
by an unrelated project); the import name is `latex2md`. From a checkout:
`pip install -e .`.

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

```bash
latex2md to-md 2401.12345.tar.gz -o paper.md   # arXiv source archive (.zip/.tar/.tar.gz/.tgz)
```

```bash
latex2md flatten main.tex -o flat.tex          # one .tex with includes inlined
```

- With no input file, or `-`, it reads stdin. With no `-o`, it writes to stdout.
- `auto` picks the direction from the extension (`.md/.markdown` or `.tex/.latex/.ltx`).
- `--standalone` (for `to-latex` and `auto`) writes a complete document with a preamble.
- `--base-dir DIR` (for `to-md` and `auto`) is the folder `\input`/`\include` may read from.
  It defaults to the input file's folder (or the current folder for stdin).
- `--anchors`, `--cite-style keep|rendered` and `--csl FILE` (for `to-md` and `auto`)
  match the Python options below.
- Warnings (see below) are printed to stderr; `--quiet` hides them and `--strict`
  exits with status 1 when there are any.

## Python

```python
from pathlib import Path

from latex2md import flatten_latex, latex_archive_to_md, latex_file_to_md, latex_to_md, md_to_latex

tex = md_to_latex("# Title\n\nEnergy is $E = mc^2$ [@einstein1905].")
md = latex_to_md(r"\section{Title} Energy is $E = mc^2$ \cite{einstein1905}.")
full = md_to_latex(markdown_text, standalone=True)

# Multi-file projects (e.g. an unpacked arXiv source archive):
md = latex_file_to_md("paper/main.tex")                      # YAML front matter
md = latex_file_to_md("paper/main.tex", front_matter=False)  # abstract as a section
md = latex_to_md(tex_text, base_dir="paper/")                # text + project folder

# Source archives as downloaded from arXiv (bytes):
md = latex_archive_to_md(Path("2401.12345.tar.gz").read_bytes())

# The pre-pandoc pipeline only: one LaTeX file, includes inlined.
flat = flatten_latex(Path("paper/main.tex"))   # a Path is a file ...
flat = flatten_latex(tex_text, base_dir="paper/")  # ... a str is LaTeX source
```

All errors (pandoc missing, failing or timing out) raise `ConversionError`; its
`.stderr` holds pandoc's message.

### Archives

`open_latex_archive(data, limits=ArchiveLimits())` is a context manager that
unpacks a zip, tar, tar.gz/bz2/xz, a single gzip'd `.tex` (arXiv serves these
for one-file papers) or a bare `.tex` into a private temporary folder, and
yields `(root_dir, main_tex)`. The folder is deleted afterwards.

```python
from latex2md import ArchiveLimits, latex_file_to_md, open_latex_archive

with open_latex_archive(data, limits=ArchiveLimits(max_total_bytes=50_000_000)) as (root, main_tex):
    md = latex_file_to_md(main_tex, base_dir=root)
```

The main file is the one named `toplevel` in arXiv's `00README.json`, else a
`.tex` with both `\documentclass` and `\begin{document}` (preferring
`main`/`paper`/`ms`, then the shallowest), else `main`/`paper`/`ms.tex`, else
the shallowest `.tex`.

| `ArchiveLimits` field | Default |
|---|---|
| `max_total_bytes` (all extracted files) | 200 MB |
| `max_members` | 2,000 |
| `max_file_bytes` (one file) | 50 MB |
| `max_ratio` (extracted / archive size, checked after the first 1 MB) | 100 |

Limits are checked on the bytes actually decompressed, while streaming, not
on sizes claimed in headers. Exceeding one, or invalid data, raises
`ArchiveError` (a `ConversionError`). Symlinks, hard links, devices and
members with absolute or `..` paths are skipped and reported as
`skipped_member` warnings.

### Warnings

Each `str` function has a `convert_*` twin that returns a `ConversionResult`
with the text and a list of `ConversionWarning(kind, message, location)`:

```python
from latex2md import convert_latex_file_to_md

result = convert_latex_file_to_md("paper/main.tex")
print(result.text)
for warning in result.warnings:
    print(warning.kind, warning.message, warning.location)
```

| Kind | Raised when |
|---|---|
| `skipped_member` | an archive member was not extracted (link, device, path outside the archive) |
| `skipped_include` | an include was not inlined: absolute path, outside the base folder, missing, cycle, nesting too deep, size budget used up, or no base folder |
| `unknown_command` | pandoc skipped a command it does not know (layout-only commands such as `\centering` are not reported) |
| `unknown_environment` | pandoc did not know an environment; its content is kept |
| `missing_bibliography` | `\bibliography`/`\addbibresource` has no `.bbl` or readable `.bib` |
| `bibliography` | a `.bib` entry was malformed and left out |
| `unresolved_reference` | `\ref`/`\eqref`/`\cref` names a label that does not exist |
| `dropped_image` | `md_to_latex` removed an image it may not reference |
| `pandoc` | any other pandoc `[WARNING]` |

Locations of `unknown_*` warnings are line numbers in the flattened source
(see `flatten_latex`), since includes have already been inlined. Unknown
commands in the preamble are not reported.

## What it handles

| | Markdown → LaTeX | LaTeX → Markdown |
|---|---|---|
| Headings | `\section{}` + `\label{}` | `#`, `##`, … (labels dropped) |
| Math | `\( \)` and `\[ \]` | `$…$` and `$$…$$` |
| Chemistry (`\ce{}`) | kept; `--standalone` loads `mhchem` | kept inside math |
| Citations | `[@key]` → `\cite{key}` (or natbib, biblatex, citeproc) | `\cite{key}` → `[@key]` (or rendered by citeproc) |
| Lists | `itemize` / `enumerate` | tight `-` / `1.` lists |
| Tables | `longtable` (needs `longtable` + `booktabs`) | pipe tables; first row becomes header |
| Code | `verbatim` | fenced blocks |
| Comments | — | `%` comments removed; `\%`, `\verb` and verbatim kept |
| Multi-file projects | — | `\input`, `\include`, `\subfile`, `\import`, `\lstinputlisting` inlined from the project folder |
| Title, authors, abstract | — | YAML front matter, or an "Abstract" section with `front_matter=False` |
| Macros (`\newcommand`) | — | expanded |
| Images | checked against `resource_dir` (see below) | path kept |
| Templates | `template=` + `variables=` | — |
| Floats | — | `figure` → image with "Figure 2: caption" as alt text; subfigures → one image each with "(a) caption", then "**Figure 2:** caption"; `table` → "**Table 1:** caption" + pipe table |
| Equation numbers | — | numbered as in LaTeX, written as `\tag{n}` (see below) |
| Cross-references | — | `\ref`, `\eqref`, `\autoref`, `\cref`, `\Cref`, `\subref` → the number LaTeX would print |
| Theorems (amsthm) | — | `**Theorem 1 (Name).** body`, numbered per `\newtheorem`; `proof` → `*Proof.* … ∎` |
| Algorithms | — | "**Algorithm 1:** caption" + a fenced `text` block of indented pseudo-code |
| Unknown environments | — | content kept, `unknown_environment` warning |
| Bibliography | — | `thebibliography` → "References" list; a sibling `.bbl` fills `\bibliography{}`; otherwise a `.bib` in the project is rendered by citeproc (see below) |

Fragment output (the default) avoids macros that only pandoc's template defines
(`\tightlist`, `Shaded`, `\hypertarget`), so it compiles in an ordinary preamble. Standalone output uses pandoc's
template, which loads `lmodern` (Debian/Ubuntu: the `lmodern` package).

## Safety

LaTeX can name any file on disk (`\input{/etc/passwd}`), so latex2md never lets
pandoc read files itself: pandoc always runs with `--sandbox`, and latex2md
inlines includes only when they resolve inside the base folder. Absolute paths,
`..` escapes, symlinks pointing outside, cycles, nesting deeper than 16 levels and
more than 20 MB of included files are skipped. Without a base folder, include
commands are removed. Archives are unpacked under the limits above. This makes
it safe to run on untrusted uploads.

## Markdown → LaTeX options

```python
tex = md_to_latex(
    markdown_text,
    template="paper/template.latex",          # a pandoc template; implies standalone
    variables={"classoption": "twocolumn"},    # its $variables$
    citations="citeproc",                      # "cite" (default), "natbib", "biblatex", "citeproc"
    bibliography="paper/refs.bib",             # .bib or CSL JSON
    csl="paper/ieee.csl",                      # citeproc style
    resource_dir="paper/",                     # images, template, bibliography and CSL must be inside
    allow_remote_images=False,                 # default
)
```

```bash
latex2md to-latex notes.md --template t.latex -V classoption=twocolumn \
    --citations citeproc --bibliography refs.bib --csl ieee.csl --resource-dir .
```

| `citations` | `[@a; @b]` / `@a` become | Bibliography |
|---|---|---|
| `cite` (default) | `\cite{a, b}` / `\citet{a}` | — |
| `natbib` | `\citep{a, b}` / `\citet{a}` | standalone: `\bibliography{refs}` |
| `biblatex` | `\autocite{a,b}` / `\textcite{a}` | standalone: `\addbibresource{refs.bib}` + `\printbibliography` |
| `citeproc` | rendered text, e.g. "(Knuth 1984)" | a "References" list (needs `bibliography`) |

`.bib` files go through the same malformed-entry handling as LaTeX → Markdown.

**Images** are checked before pandoc writes LaTeX, so the output never points
the TeX run at files it should not read:

- `data:` URIs pass the check, but pandoc's LaTeX writer cannot embed them, so
  they are reported as `dropped_image` too;
- local paths are kept when they resolve (symlinks included) to an existing
  file inside `resource_dir`; without `resource_dir`, relative paths that do
  not climb out with `..` are kept;
- `http(s)` URLs are kept only with `allow_remote_images=True`;
- everything else (absolute paths, `..`, `file:` and other schemes) is
  replaced by its alt text (a figure keeps its caption) and reported as a
  `dropped_image` warning.

`template`, `bibliography` and `csl` must be existing regular files, inside
`resource_dir` when one is given; otherwise `ConversionError` is raised.

## Bibliographies

A compiled `.bbl` (arXiv ships one next to the main file) is used as is; a
biblatex `.bbl` (biber's data format) is read and printed as a reference list
where `\printbibliography` stood. When
there is none, the `.bib` files named by `\bibliography{refs}` or
`\addbibresource{refs.bib}` are looked up inside the base folder and rendered
by pandoc's citeproc as a "References" list where `\bibliography`/`\printbibliography`
stood:

```python
md = latex_file_to_md("paper/main.tex")                           # [@key] kept in the text
md = latex_file_to_md("paper/main.tex", cite_style="rendered")    # "(Knuth 1984)"
md = latex_file_to_md("paper/main.tex", csl="paper/ieee.csl")      # a CSL style; default: pandoc's built-in
md = latex_to_md(tex_text, base_dir="paper/")                     # works for text input too
```

```bash
latex2md to-md paper/main.tex --cite-style rendered --csl paper/ieee.csl
```

The `.bib` must be a regular file inside the base folder (no absolute paths,
`..` or symlinks out; at most 10 MB and 16 files), and `csl` must be an
existing file inside the base folder when one is given; otherwise the `.bib`
is reported as `missing_bibliography` and an unsafe `csl` raises
`ConversionError`. pandoc rejects a whole `.bib` for one bad entry, so
malformed entries (unbalanced braces, no key, or anything pandoc cannot parse)
are left out and reported as `bibliography` warnings; if the file is still
unreadable, the conversion continues without citeproc.

## Numbering and cross-references

LaTeX → Markdown numbers things the way LaTeX does, in document order, and
replaces references with those numbers:

- **Equations:** `equation`, `align`, `gather`, `multline`, `alignat`, `flalign`
  and `eqnarray` are numbered; starred environments and rows with
  `\nonumber`/`\notag` are not; `\tag{x}` is respected; `\numberwithin` and
  book/report chapters give "2.3". The number is written as `\tag{n}` at the
  end of the `$$…$$` block, which KaTeX and MathJax render. `align` becomes
  `aligned`, and since KaTeX cannot tag rows of `aligned`, a block with several
  numbered rows carries **one tag with the range**, e.g. `\tag{1–2}`; each row's
  `\label` still resolves to its own number. `\label` never stays in math.
- **Sections** (including `\appendix` → A, B), **figures**, **subfigures** (1a),
  **tables**, **theorems**, **algorithms**, algorithm lines and `enumerate` items
  get numbers too.
- `\ref{x}` → `3`; `\ref`/`\eqref` to an equation → `(4)`; `\autoref`, `\cref`,
  `\Cref` → "Section 3", "Figure 2", "Table 1", "Equation (4)", "Theorem 2.1",
  "Algorithm 1"; `\cref{a,b}` → "Sections 1 and 2"; `\subref` → "(a)".
- A label that does not exist becomes `(label)` and an `unresolved_reference` warning.

`anchors=True` (`latex_to_md`, `latex_file_to_md`, `latex_archive_to_md`)
links references to **sections** to their heading: `Section [3](#method)`.
The link target is the heading's GitHub-style id (lower case, punctuation
removed, spaces → `-`, `-1`, `-2`… for repeated titles), which GitHub, GitLab,
VS Code and most Markdown renderers generate on their own; nothing is added to
the heading, so the output stays plain Markdown with no HTML or `{#id}`
attributes. Plain Markdown has no anchor syntax for equations, figures or
tables, so references to those stay text.

## Limitations

- Custom macros and unusual packages in LaTeX are only as good as pandoc's LaTeX reader;
  unknown commands are dropped.
- Pseudo-code in algorithms is not macro-expanded, and `subequations` are numbered
  as ordinary equations.
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

CI runs the tests on Python 3.11, 3.13 and 3.14 with Ubuntu's pandoc and
pandoc 3.6.4, plus two more jobs:

- **compile**: `python scripts/compile_check.py` converts the Markdown fixtures
  and LaTeX → Markdown → LaTeX round trips to standalone documents (and the
  Markdown fixture as a fragment in a plain preamble) and compiles each with
  `latexmk -pdf -interaction=nonstopmode`. It needs TeX Live
  (`texlive-latex-recommended texlive-latex-extra texlive-science lmodern latexmk`;
  pandoc's standalone template loads `lmodern`, which minimal installs leave out).
- **corpus**: ten real arXiv papers (cs, math, astro-ph, q-bio, quant-ph),
  listed in `tests/corpus/manifest.json` with their licence, the sha256 of the
  e-print and structural expectations (heading range, minimum display
  equations, tables and references). Only papers whose arXiv licence is
  CC BY 4.0 or CC0 (read from the abs page) are listed; the e-prints are
  downloaded into a gitignored cache (`tests/corpus/cache/`, or
  `LATEX2MD_CORPUS_CACHE`), never committed.

```bash
python scripts/fetch_corpus.py                    # download and verify the e-prints
LATEX2MD_CORPUS=1 pytest tests/test_corpus.py     # convert and check them
python scripts/fetch_corpus.py --check-licences   # re-check licences on arxiv.org
python scripts/fetch_corpus.py --add 2402.18824v1 --pandoc pandoc --pandoc /path/to/pandoc-3.6.4
```

`--add` refuses papers that are not CC BY 4.0/CC0, downloads the versioned
e-print, converts it with each pandoc and prints a manifest entry with the
measurements and expectations to paste into the manifest. The corpus test
also checks that the Markdown has no `\begin{`/`\end{` outside math and code,
no `<div` and no `:::`.

## Releasing

Releases are automatic. To publish a new version:

1. Bump `version` in `pyproject.toml` and `__version__` in `src/latex2md/__init__.py`
   (the workflow fails if they differ).
2. Merge that change into `main`.

On every push to `main`, the `release` workflow checks whether the tag `v<version>`
exists. If it does not, it runs the tests, builds, publishes to PyPI with trusted
publishing, and only then creates the `v<version>` tag and a GitHub release with the
built files. Merges that do not change the version publish nothing.

Pushing a matching `v*` tag by hand still works as a fallback; an already-published
version is skipped rather than uploaded twice. The one-time PyPI setup is described at
the top of `.github/workflows/release.yml`.

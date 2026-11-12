"""Read biblatex's ``.bbl`` (biber's data file) into a ``thebibliography`` list.

A natbib/BibTeX ``.bbl`` is ordinary LaTeX (``thebibliography``), so it can be
inlined. A biblatex ``.bbl`` is not: it is a data dump (``\\refsection``,
``\\entry``, ``\\field``...) wrapped in ``\\@latex@error``/``\\endinput``
guards, and inlining it makes pandoc drop the whole document. arXiv ships
such files for biblatex papers, so their entries are rendered here as a
simple "Authors. Title. Journal, volume, pages, year." list.
"""
from __future__ import annotations

import re

from latex2md.texscan import read_group

_ENTRY_RE = re.compile(r"\\entry\s*\{([^{}]*)\}\s*\{([^{}]*)\}\s*\{[^{}]*\}(.*?)\\endentry", re.DOTALL)
_FIELD_RE = re.compile(r"\\(field|list|name|verb)\s*\{(\w+)\}")
_PERIOD_MACROS_RE = re.compile(r"\\bib(?:initperiod|initdelim|namedelim[a-z]?|rangedash|nbsp)\b\s*")


def is_biblatex_bbl(bbl: str) -> bool:
    return "\\refsection" in bbl or ("\\entry{" in bbl and "\\endentry" in bbl)


def _clean(text: str) -> str:
    text = _PERIOD_MACROS_RE.sub(lambda m: "-" if "rangedash" in m.group(0) else " ", text)
    return re.sub(r"\s+", " ", text.replace("%\n", "")).strip()


def _names(block: str) -> list[str]:
    names = []
    for family, given in re.findall(r"family=\{((?:[^{}]|\{[^{}]*\})*)\}(?:.*?given=\{((?:[^{}]|\{[^{}]*\})*)\})?", block, re.DOTALL):
        family, given = _clean(family), _clean(given)
        names.append(f"{given} {family}".strip() if given else family)
    return names


def _fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    position = 0
    while match := _FIELD_RE.search(body, position):
        kind, name = match.group(1), match.group(2)
        position = match.end()
        if kind in ("list", "name"):
            # \name{author}{n}{options}{...} but \list{publisher}{n}{...}
            count = read_group(body, position)
            extra = read_group(body, count[1]) if count and kind == "name" else count
            value = read_group(body, extra[1]) if extra else None
            if value is None:
                continue
            position = value[1]
            if kind == "name":
                fields[name] = ", ".join(_names(value[0]))
            else:
                items = re.findall(r"\{((?:[^{}]|\{[^{}]*\})*)\}", value[0])
                fields[name] = ", ".join(_clean(item) for item in items)
            continue
        if kind == "verb":
            end = body.find("\\endverb", position)
            if end == -1:
                continue
            # \verb{doi}\n\verb 10.1000/x\n\endverb: each line repeats \verb.
            fields[name] = re.sub(r"\\verb\s?", "", body[position:end]).strip()
            position = end + len("\\endverb")
            continue
        value = read_group(body, position)
        if value is not None:
            fields[name] = _clean(value[0])
            position = value[1]
    return fields


def _render(fields: dict[str, str]) -> str:
    parts = []
    if fields.get("author") or fields.get("editor"):
        parts.append(fields.get("author") or fields["editor"])
    if fields.get("title"):
        parts.append(f"\\emph{{{fields['title']}}}" if not fields.get("journaltitle") else fields["title"])
    venue = [fields.get(k) for k in ("journaltitle", "booktitle", "howpublished", "publisher", "organization")]
    details = [v for v in venue if v]
    if fields.get("volume"):
        details.append(fields["volume"] + (f"({fields['number']})" if fields.get("number") else ""))
    if fields.get("pages"):
        details.append(fields["pages"])
    year = fields.get("year") or (fields.get("date") or "")[:4]
    if year:
        details.append(year)
    if details:
        parts.append(", ".join(details))
    if fields.get("note"):
        parts.append(fields["note"])
    text = ". ".join(part.rstrip(".") for part in parts) + "."
    if fields.get("doi"):
        text += f" \\url{{https://doi.org/{fields['doi']}}}"
    elif fields.get("url"):
        text += f" \\url{{{fields['url']}}}"
    return text


def biblatex_bbl_to_thebibliography(bbl: str) -> str:
    """The entries of a biblatex ``.bbl`` as a ``thebibliography`` environment."""
    items = [f"\\bibitem{{{key}}} {_render(_fields(body))}" for key, _, body in _ENTRY_RE.findall(bbl)]
    return "\\begin{thebibliography}{99}\n" + "\n".join(items) + "\n\\end{thebibliography}\n"

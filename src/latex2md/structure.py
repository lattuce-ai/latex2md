"""Numbering, cross-references and environments, resolved before pandoc.

Markdown has no counters, so ``\\ref``/``\\eqref`` must become the numbers a
reader of the PDF would see. pandoc cannot do that: it turns ``align`` and
``align*`` into the same math, forgets ``\\nonumber``, does not know shared
theorem counters, and drops pseudo-code. This pass walks the LaTeX body in
document order the way LaTeX does (``\\label`` refers to the most recent
numbered thing in the current group) and rewrites the source:

- numbered display math becomes ``\\[ ... \\tag{n} \\]`` with ``\\label``,
  ``\\nonumber`` and ``\\notag`` removed (multi-row ``align`` becomes
  ``aligned`` with one tag for the block, since KaTeX cannot tag rows of
  ``aligned``);
- captions get "Figure n: ", "Table n: " or "(a) " prefixes;
- amsthm theorems and proofs become bold/italic run-in headings;
- algorithms become a caption line and a verbatim block of pseudo-code;
- ``\\ref``, ``\\eqref``, ``\\autoref``, ``\\cref``, ``\\Cref`` and
  ``\\subref`` become text, or ``\\href`` links to headings with ``anchors``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from latex2md.algorithms import (
    format_algorithm2e,
    format_algorithmic,
    looks_like_algorithm2e,
)
from latex2md.result import ConversionWarning
from latex2md.texscan import (
    VERBATIM_ENVS,
    escape_text,
    find_env_end,
    protect_verbatim,
    read_group,
    read_optional,
    restore_verbatim,
    split_top_level,
)

MATH_ENVS = frozenset({"equation", "align", "gather", "multline", "flalign", "alignat", "xalignat", "eqnarray"})
_MULTI_ROW = frozenset({"align", "gather", "flalign", "alignat", "xalignat", "eqnarray"})
_INNER_ENV = {
    "align": "aligned",
    "flalign": "aligned",
    "eqnarray": "aligned",
    "gather": "gathered",
    "multline": "gathered",
    "alignat": "alignedat",
    "xalignat": "alignedat",
}
_FLOATS = {
    "figure": "figure", "figure*": "figure", "wrapfigure": "figure", "sidewaysfigure": "figure",
    "table": "table", "table*": "table", "wraptable": "table", "sidewaystable": "table", "longtable": "table",
    "subfigure": "subfigure", "subtable": "subtable",
}
_SECTION_LEVELS = ("chapter", "section", "subsection", "subsubsection")
_DEFAULT_THEOREMS = {
    name: name.capitalize()
    for name in (
        "theorem", "lemma", "proposition", "corollary", "definition", "remark", "example", "conjecture",
        "claim", "assumption", "observation", "fact", "hypothesis", "problem", "exercise", "question", "notation",
    )
}
_CHAPTER_CLASSES = re.compile(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{\s*(?:book|report|memoir|scrbook|scrreprt)\s*\}")
_TOKEN_RE = re.compile(
    r"\\\\"
    r"|\\(?P<be>begin|end)\s*\{(?P<env>[^{}]+)\}"
    r"|\\(?P<sec>part|chapter|section|subsection|subsubsection|paragraph|subparagraph)(?![A-Za-z])(?P<star>\*?)"
    r"|\\(?P<appendix>appendix)(?![A-Za-z])"
    r"|\\(?P<caption>caption(?:of)?)(?![A-Za-z])(?P<capstar>\*?)"
    r"|\\(?P<label>label)\s*(?=\{)"
    r"|\\(?P<subfloat>subfloat)(?![A-Za-z])"
    r"|\\(?P<item>item)(?![A-Za-z])"
    r"|\\verb\*?(?P<verb>[^a-zA-Z\s*])"
)
_REF_RE = re.compile(r"\\(?P<cmd>ref|eqref|autoref|cref|Cref|subref|vref|Vref|cpageref|labelcref)(?P<star>\*?)\s*\{(?P<labels>[^{}]*)\}")
_HYPERREF_RE = re.compile(r"\\hyperref\s*\[(?P<label>[^\]]*)\]\s*\{")
_ROW_TAG_RE = re.compile(r"[ \t]*\\tag\*?\s*\{((?:[^{}]|\{[^{}]*\})*)\}")
_ROW_LABEL_RE = re.compile(r"[ \t]*\\label\s*\{([^{}]*)\}")
# A caption that already starts with its label (Markdown that went through
# latex2md once) is not prefixed again, so round trips are stable.
_LABELLED_CAPTION_RE = re.compile(r"^\s*(?:(?:Figure|Table)[\s~]+[A-Z]?[\d.]*\d[a-z]?:|\([a-z]{1,3}\))\s")
_ROW_NONUMBER_RE = re.compile(r"[ \t]*\\(?:nonumber|notag)(?![A-Za-z])")


@dataclass(frozen=True)
class Target:
    """What a label points at: a kind ("section", "equation", a theorem title, ...) and its number."""

    kind: str
    number: str
    name: str



def _alph(n: int) -> str:
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("a") + rem) + out
    return out or "0"


@dataclass
class _Theorem:
    title: str
    counter: str | None  # None: unnumbered (\newtheorem*)
    within: str | None = None  # \newtheorem{thm}{Theorem}[section]


@dataclass
class _Counters:
    has_chapters: bool
    value: dict[str, int] = field(default_factory=dict)
    within: dict[str, str | None] = field(default_factory=dict)
    alias: dict[str, str] = field(default_factory=dict)
    appendix: bool = False

    def __post_init__(self) -> None:
        chapter = "chapter" if self.has_chapters else None
        self.within.update(
            {
                "section": chapter,
                "subsection": "section",
                "subsubsection": "subsection",
                "figure": chapter,
                "table": chapter,
                "equation": chapter,
                "algorithm": chapter,
            }
        )

    def real(self, name: str) -> str:
        seen = set()
        while name in self.alias and name not in seen:
            seen.add(name)
            name = self.alias[name]
        return name

    def reset(self, name: str) -> None:
        self.value[name] = 0
        for child, parent in self.within.items():
            if parent == name and self.value.get(child):
                self.reset(child)

    def step(self, name: str) -> str:
        name = self.real(name)
        self.value[name] = self.value.get(name, 0) + 1
        for child, parent in self.within.items():
            if parent == name:
                self.reset(child)
        return self.format(name)

    def peek(self, name: str) -> str:
        name = self.real(name)
        self.value[name] = self.value.get(name, 0) + 1
        try:
            return self.format(name)
        finally:
            self.value[name] -= 1

    def format(self, name: str) -> str:
        name = self.real(name)
        value = self.value.get(name, 0)
        top = "chapter" if self.has_chapters else "section"
        own = chr(ord("A") + value - 1) if self.appendix and name == top and 0 < value <= 26 else str(value)
        parent = self.within.get(name)
        return f"{self.format(parent)}.{own}" if parent else own


def _theorem_definitions(source: str) -> dict[str, _Theorem]:
    """Read ``\\newtheorem`` and ``\\declaretheorem`` declarations."""
    theorems: dict[str, _Theorem] = {}
    pattern = re.compile(r"\\newtheorem(\*?)\s*\{([^{}]+)\}")
    for match in pattern.finditer(source):
        star, env = match.group(1), match.group(2).strip()
        position = match.end()
        shared = read_optional(source, position)
        if shared:
            position = shared[1]
        title = read_group(source, position)
        if title is None:
            continue
        position = title[1]
        within = None if shared else read_optional(source, position)
        counter = None if star else (shared[0].strip() if shared else env)
        theorems[env] = _Theorem(title[0].strip(), counter, within[0].strip() if within else None)
    for match in re.finditer(r"\\declaretheorem\s*(?:\[([^\]]*)\])?\s*\{([^{}]+)\}", source):
        options = dict(
            (part.split("=", 1) + [""])[:2] for part in (match.group(1) or "").replace(" ", "").split(",") if part
        )
        env = match.group(2).strip()
        title = options.get("name") or options.get("title") or env.capitalize()
        shared = options.get("sibling") or options.get("sharenumber") or options.get("numberlike")
        counter = None if options.get("numbered") == "no" else (shared or env)
        theorems[env] = _Theorem(title, counter, options.get("numberwithin") or options.get("parent"))
    return theorems


class StructurePass:
    """Rewrite one LaTeX document; see the module docstring."""

    def __init__(self, source: str, *, anchors: bool = False) -> None:
        self.anchors = anchors
        self.counters = _Counters(has_chapters=bool(_CHAPTER_CLASSES.search(source) or "\\chapter" in source))
        self.labels: dict[str, Target] = {}
        self.current: Target | None = None
        self.stack: list[tuple[str, Target | None, str]] = []  # (env, saved target, role)
        self.blocks: list[str] = []  # algorithm text, resolved after labels are known
        self.warnings: list[ConversionWarning] = []
        self.theorems = {name: _Theorem(title, name) for name, title in _DEFAULT_THEOREMS.items()}
        for env, theorem in _theorem_definitions(source).items():
            self.theorems[env] = theorem
            if theorem.counter and theorem.counter != env:
                self.counters.alias[env] = theorem.counter
            if theorem.counter == env and theorem.within:
                self.counters.within[env] = theorem.within
        for counter, parent in re.findall(r"\\(?:numberwithin|counterwithin\*?)\s*\{([^{}]+)\}\s*\{([^{}]+)\}", source):
            self.counters.within[counter.strip()] = parent.strip()
        self.enum_depth = 0
        self.figure_number = ""

    # -- helpers -------------------------------------------------------------

    def _set(self, kind: str, number: str, name: str) -> Target:
        self.current = Target(kind, number, name)
        return self.current

    def _float_kind(self) -> str | None:
        for env, _, role in reversed(self.stack):
            if role == "float":
                return _FLOATS[env]
            if role == "algorithm":
                return "algorithm"
        return None

    # -- the walk ------------------------------------------------------------

    def process(self, text: str) -> str:
        out: list[str] = []
        position = 0
        while match := _TOKEN_RE.search(text, position):
            out.append(text[position : match.start()])
            position = match.end()
            if match.group(0) == "\\\\":
                out.append(match.group(0))
            elif match.group("verb"):
                end = text.find(match.group("verb"), position)
                end = len(text) if end == -1 else end + 1
                out.append(text[match.start() : end])
                position = end
            elif match.group("be") == "begin":
                replacement, position = self._begin(text, match, position)
                out.append(replacement)
            elif match.group("be") == "end":
                out.append(self._end(match.group("env").strip(), match.group(0)))
            elif match.group("sec"):
                self._section(match.group("sec"), bool(match.group("star")))
                out.append(match.group(0))
            elif match.group("appendix"):
                self.counters.appendix = True
                self.counters.reset("chapter" if self.counters.has_chapters else "section")
                out.append(match.group(0))
            elif match.group("caption"):
                replacement, position = self._caption(text, match, position)
                out.append(replacement)
            elif match.group("label"):
                group = read_group(text, position)
                if group is None:
                    out.append(match.group(0))
                    continue
                if self.current is not None:
                    self.labels.setdefault(group[0].strip(), self.current)
                out.append(text[match.start() : group[1]])
                position = group[1]
            elif match.group("subfloat"):
                replacement, position = self._subfloat(text, position)
                out.append(replacement)
            elif match.group("item"):
                if self._innermost_list() == "enumerate":
                    self._enum_item()
                out.append(match.group(0))
        out.append(text[position:])
        return "".join(out)

    def _innermost_list(self) -> str | None:
        for env, _, _ in reversed(self.stack):
            if env in ("enumerate", "itemize", "description"):
                return env
        return None

    def _enum_item(self) -> None:
        depth = sum(1 for env, _, _ in self.stack if env == "enumerate")
        name = f"enum{depth}"
        self.counters.within.setdefault(name, f"enum{depth - 1}" if depth > 1 else None)
        number = self.counters.step(name)
        parts = number.split(".")
        label = parts[0] + "".join(_alph(int(p)) if k == 1 else f".{p}" for k, p in enumerate(parts[1:], 1))
        self._set("item", label, "Item")

    def _section(self, level: str, starred: bool) -> None:
        if starred or level not in _SECTION_LEVELS:
            return
        if level == "chapter" and not self.counters.has_chapters:
            return
        number = self.counters.step(level)
        if level == "chapter":
            name = "Appendix" if self.counters.appendix else "Chapter"
        else:
            name = "Appendix" if self.counters.appendix else "Section"
        self._set("section", number, name)

    def _begin(self, text: str, match: re.Match[str], position: int) -> tuple[str, int]:
        env = match.group("env").strip()
        base = env.rstrip("*")
        if env in VERBATIM_ENVS:
            end = find_env_end(text, env, position)
            stop = end[1] if end else len(text)
            return text[match.start() : stop], stop
        if base in MATH_ENVS:
            end = find_env_end(text, env, position)
            if end is not None:
                return self._display_math(base, env.endswith("*"), text, position, end[0]), end[1]
        if base == "algorithm" or env == "algorithm2e":
            end = find_env_end(text, env, position)
            if end is not None:
                return self._algorithm(text[position : end[0]]), end[1]
        if env == "algorithmic":
            end = find_env_end(text, env, position)
            if end is not None:
                return self._algorithmic_block(text, position, end[0]), end[1]
        saved = self.current
        if env in self.theorems:
            return self._theorem(env, text, position, saved)
        if env == "proof":
            optional = read_optional(text, position)
            title = f"{optional[0].strip().rstrip('.')}." if optional else "Proof."
            self.stack.append((env, saved, "proof"))
            return f"\\par\\emph{{{title}}} ", optional[1] if optional else position
        if env in _FLOATS:
            self.stack.append((env, saved, "float"))
            if _FLOATS[env] == "figure":
                self.figure_number = self.counters.peek("figure")
                self.counters.value["subfigure"] = 0
            if _FLOATS[env] in ("subfigure", "subtable"):
                # Drop [pos]{width}: pandoc reads \begin{subfigure}{} and skips \linewidth noisily.
                j = position
                optional = read_optional(text, j)
                if optional:
                    j = optional[1]
                width = read_group(text, j)
                if width:
                    j = width[1]
                return "\\begin{subfigure}{}", j
            return match.group(0), position
        role = "enumerate" if env == "enumerate" else "env"
        self.stack.append((env, saved, role))
        return match.group(0), position

    def _end(self, env: str, raw: str) -> str:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == env:
                _, saved, role = self.stack[index]
                del self.stack[index:]
                self.current = saved
                if env == "enumerate":
                    depth = sum(1 for e, _, _ in self.stack if e == "enumerate") + 1
                    self.counters.reset(f"enum{depth}")
                if role == "theorem":
                    return "\\par "
                if role == "proof":
                    return " ∎\\par "
                if role == "float" and _FLOATS[env] in ("subfigure", "subtable"):
                    return "\\end{subfigure}"
                return raw
        return raw

    def _theorem(self, env: str, text: str, position: int, saved: Target | None) -> tuple[str, int]:
        theorem = self.theorems[env]
        optional = read_optional(text, position)
        if optional:
            position = optional[1]
        head = theorem.title
        if theorem.counter:
            number = self.counters.step(env)
            head = f"{head} {number}"
            self.stack.append((env, saved, "theorem"))
            self._set("theorem", number, theorem.title)
        else:
            self.stack.append((env, saved, "theorem"))
        if optional and optional[0].strip():
            head = f"{head} ({self.process(optional[0].strip())})"
        return f"\\par\\textbf{{{head}.}} ", position

    def _caption(self, text: str, match: re.Match[str], position: int) -> tuple[str, int]:
        kind = None
        if match.group("caption") == "captionof":
            group = read_group(text, position)
            if group is None:
                return match.group(0), position
            kind, position = group[0].strip().rstrip("*"), group[1]
        else:
            kind = self._float_kind()
        optional = read_optional(text, position)
        if optional:
            position = optional[1]
        group = read_group(text, position)
        if group is None:
            return match.group(0), position
        position = group[1]
        if match.group("capstar") or kind not in ("figure", "table", "subfigure", "subtable", "algorithm"):
            return f"\\caption{{{self.process(group[0])}}}", position
        prefix = self._step_caption(kind)
        if _LABELLED_CAPTION_RE.match(group[0]):
            prefix = ""
        body = self.process(group[0])
        if match.group("caption") == "captionof":
            return f"\\par\\textbf{{{prefix.rstrip(': ').strip()}:}} {body}\\par ", position
        return f"\\caption{{{prefix}{body}}}", position

    def _step_caption(self, kind: str) -> str:
        if kind in ("subfigure", "subtable"):
            parent = "figure" if kind == "subfigure" else "table"
            self.counters.value[kind] = self.counters.value.get(kind, 0) + 1
            letter = _alph(self.counters.value[kind])
            base = self.figure_number if parent == "figure" else self.counters.peek("table")
            self._set(parent, f"{base}{letter}", parent.capitalize())
            return f"({letter}) "
        number = self.counters.step(kind)
        self._set(kind, number, kind.capitalize())
        return f"{kind.capitalize()} {number}: "

    def _subfloat(self, text: str, position: int) -> tuple[str, int]:
        first = read_optional(text, position)
        second = read_optional(text, first[1]) if first else None
        caption = second or first
        j = caption[1] if caption else position
        body = read_group(text, j)
        if body is None:
            return "\\subfloat", position
        saved = self.current
        prefix = self._step_caption("subfigure") if caption and caption[0].strip() else ""
        caption_text = self.process(caption[0]) if caption else ""
        inner = self.process(body[0])
        self.current = saved
        caption_tex = f"\\caption{{{prefix}{caption_text}}}" if prefix else ""
        return f"\\begin{{subfigure}}{{}}{inner}{caption_tex}\\end{{subfigure}}", body[1]

    # -- display math --------------------------------------------------------

    def _display_math(self, base: str, starred: bool, text: str, start: int, end: int) -> str:
        body = text[start:end]
        prefix = ""
        if base in ("alignat", "xalignat"):
            columns = read_group(body, 0)
            if columns:
                prefix = f"{{{columns[0]}}}"
                body = body[columns[1] :]
        rows = split_top_level(body) if base in _MULTI_ROW else [(body, "")]
        numbers: list[str] = []
        cleaned: list[str] = []
        for row, separator in rows:
            tag = _ROW_TAG_RE.search(row)
            labels = _ROW_LABEL_RE.findall(row)
            numbered = not starred and not _ROW_NONUMBER_RE.search(row) and bool(row.strip() or labels)
            number = None
            if tag:
                number = tag.group(1).strip()
            elif numbered:
                number = self.counters.step("equation")
            if number is not None:
                numbers.append(number)
            for label in labels:
                target = Target("equation", number, "Equation") if number is not None else self.current
                if target is not None:
                    self.labels.setdefault(label.strip(), target)
            row = _ROW_LABEL_RE.sub("", _ROW_TAG_RE.sub("", _ROW_NONUMBER_RE.sub("", row)))
            cleaned.append(row + separator)
        inner = "".join(cleaned).strip()
        environment = _INNER_ENV.get(base)
        if environment:
            inner = f"\\begin{{{environment}}}{prefix}\n{inner}\n\\end{{{environment}}}"
        if numbers:
            tag = numbers[0] if len(numbers) == 1 else f"{numbers[0]}–{numbers[-1]}"
            inner = f"{inner} \\tag{{{tag}}}"
        return f"\n\\[{inner}\\]\n"

    # -- algorithms ----------------------------------------------------------

    def _algorithm(self, body: str) -> str:
        saved = self.current
        self.stack.append(("algorithm", saved, "algorithm"))
        caption_line = ""
        caption = re.search(r"\\caption\s*(?=[\[{])", body)
        if caption:
            position = caption.end()
            optional = read_optional(body, position)
            if optional:
                position = optional[1]
            group = read_group(body, position)
            if group:
                number = self.counters.step("algorithm")
                self._set("algorithm", number, "Algorithm")
                caption_line = f"\\par\\textbf{{Algorithm {number}:}} {self.process(group[0])}\\par\n"
                body = body[: caption.start()] + body[group[1] :]
        for label in re.findall(r"\\label\s*\{([^{}]*)\}", _strip_envs(body, "algorithmic")):
            if self.current is not None:
                self.labels.setdefault(label.strip(), self.current)
        inner = re.search(r"\\begin\{algorithmic\}", body)
        if inner:
            end = find_env_end(body, "algorithmic", inner.end())
            code = self._format_algorithmic(body, inner.end(), end[0] if end else len(body))
        else:
            code = self._block(format_algorithm2e(body, on_label=self._line_label) if looks_like_algorithm2e(body) else "")
        self.stack.pop()
        self.current = saved
        return f"\n{caption_line}{code}"

    def _line_label(self, label: str, line: str) -> None:
        self.labels.setdefault(label, Target("line", line, "Line"))

    def _format_algorithmic(self, text: str, start: int, end: int) -> str:
        optional = read_optional(text, start)
        numbered = bool(optional and optional[0].strip() not in ("", "0"))
        body = text[optional[1] if optional else start : end]
        return self._block(format_algorithmic(body, numbered=numbered, on_label=self._line_label))

    def _algorithmic_block(self, text: str, start: int, end: int) -> str:
        return "\n" + self._format_algorithmic(text, start, end)

    def _block(self, code: str) -> str:
        if not code.strip():
            return ""
        self.blocks.append(code)
        return f"\n\\begin{{verbatim}}\n\x00ALG{len(self.blocks) - 1}\x00\n\\end{{verbatim}}\n"

    # -- references ----------------------------------------------------------

    def _ref_text(self, command: str, labels: list[str], *, in_code: bool) -> str:
        targets = [(label, self.labels.get(label)) for label in labels]
        for label, target in targets:
            if target is None:
                self.warnings.append(
                    ConversionWarning("unresolved_reference", f"\\{command}{{{label}}}: no such \\label")
                )
        if any(target is None for _, target in targets):
            text = ", ".join(f"({label})" for label in labels)
            return text if in_code else escape_text(text)
        resolved = [target for _, target in targets if target is not None]
        numbers = [f"({t.number})" if t.kind == "equation" or command == "eqref" else t.number for t in resolved]
        if command == "subref":
            numbers = [f"({t.number.lstrip('0123456789.')})" for t in resolved]
        # \ref to an equation reads "(n)": Markdown shows the tag in parentheses.
        prefixes = [""] * len(resolved)
        if command in ("autoref", "cref", "Cref", "vref", "Vref"):
            names = {t.name for t in resolved}
            if len(names) == 1 and len(resolved) > 1:
                name = resolved[0].name
                prefixes[0] = f"{name} " if name.endswith("s") else f"{name}s "
            else:
                prefixes = [f"{t.name} " for t in resolved]
        # Numbers come from counters, names from \newtheorem and tags from
        # \tag{}: all LaTeX already, so they are not escaped. Only the number
        # is a link, so "Sections [1](#a) and [2](#b)" reads naturally.
        parts = []
        for (label, target), prefix, number in zip(targets, prefixes, numbers, strict=True):
            if self.anchors and not in_code and target is not None and target.kind == "section":
                number = f"\\href{{#{label}}}{{{number}}}"
            parts.append(prefix + number)
        return _join(parts)

    def resolve_references(self, text: str) -> str:
        protected, saved = protect_verbatim(text)

        def replace(match: re.Match[str]) -> str:
            if match.group("cmd") == "cpageref":
                return match.group(0)
            labels = [label.strip() for label in match.group("labels").split(",") if label.strip()]
            return self._ref_text(match.group("cmd"), labels, in_code=False)

        protected = _REF_RE.sub(replace, protected)
        protected = self._hyperref(protected)
        text = restore_verbatim(protected, saved)
        for index, block in enumerate(self.blocks):
            block = _REF_RE.sub(
                lambda m: self._ref_text(m.group("cmd"), [x.strip() for x in m.group("labels").split(",")], in_code=True),
                block,
            )
            text = text.replace(f"\x00ALG{index}\x00", block)
        return text

    def _hyperref(self, text: str) -> str:
        out: list[str] = []
        position = 0
        while match := _HYPERREF_RE.search(text, position):
            group = read_group(text, match.end() - 1)
            if group is None:
                break
            out.append(text[position : match.start()])
            label = match.group("label").strip()
            target = self.labels.get(label)
            if self.anchors and target is not None and target.kind == "section":
                out.append(f"\\href{{#{label}}}{{{group[0]}}}")
            else:
                out.append(group[0])
            position = group[1]
        out.append(text[position:])
        return "".join(out)


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _strip_envs(text: str, env: str) -> str:
    return re.sub(r"\\begin\{" + env + r"\}.*?\\end\{" + env + r"\}", "", text, flags=re.DOTALL)


_BEGIN_DOCUMENT_RE = re.compile(r"\\begin\s*\{document\}")


def resolve_structure(source: str, *, anchors: bool = False) -> tuple[str, list[ConversionWarning]]:
    """Number and rewrite the document body; see the module docstring."""
    walker = StructurePass(source, anchors=anchors)
    begin = _BEGIN_DOCUMENT_RE.search(source)
    # Only the body is walked: the preamble holds \newcommand bodies that
    # mention \section or equation environments without using them.
    head, body = (source[: begin.end()], source[begin.end() :]) if begin else ("", source)
    rewritten = head + walker.process(body)
    return walker.resolve_references(rewritten), walker.warnings

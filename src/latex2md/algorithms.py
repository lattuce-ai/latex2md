"""Render algorithm pseudo-code as indented plain text.

pandoc drops ``algorithmic`` and ``algorithm2e`` content almost entirely, and
there is no Markdown construct for pseudo-code. A fenced ``text`` block with
the structure spelled out ("if ... then", indented body, "end if") keeps the
algorithm readable and copyable; math stays as ``$...$``.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from latex2md.texscan import read_group, read_optional

INDENT = "    "
LabelSink = Callable[[str, str], None]

# algpseudocode/algorithmicx: name -> (argument count, role, template)
_ALGX: dict[str, tuple[int, str, str]] = {
    "State": (0, "stmt", ""),
    "Statex": (0, "stmtx", ""),
    "If": (1, "open", "if {0} then"),
    "ElsIf": (1, "mid", "else if {0} then"),
    "Else": (0, "mid", "else"),
    "EndIf": (0, "close", "end if"),
    "For": (1, "open", "for {0} do"),
    "ForAll": (1, "open", "for all {0} do"),
    "EndFor": (0, "close", "end for"),
    "While": (1, "open", "while {0} do"),
    "EndWhile": (0, "close", "end while"),
    "Loop": (0, "open", "loop"),
    "EndLoop": (0, "close", "end loop"),
    "Repeat": (0, "open", "repeat"),
    "Until": (1, "close", "until {0}"),
    "Function": (2, "open", "function {0}({1})"),
    "EndFunction": (0, "close", "end function"),
    "Procedure": (2, "open", "procedure {0}({1})"),
    "EndProcedure": (0, "close", "end procedure"),
    "Require": (0, "head", "Require:"),
    "Ensure": (0, "head", "Ensure:"),
    "Input": (0, "head", "Input:"),
    "Output": (0, "head", "Output:"),
    "Return": (0, "return", "return"),
    "Print": (0, "stmt", "print"),
    "Comment": (1, "comment", ""),
}
# The older algorithmic package spells them in capitals.
_ALGORITHMIC = {name.upper(): name for name in _ALGX} | {"ELSIF": "ElsIf", "STATEX": "Statex"}

_INLINE_WORDS = {
    "gets": "←", "leftarrow": "←", "to": "→", "rightarrow": "→",
    "TRUE": "true", "True": "true", "FALSE": "false", "False": "false",
    "AND": "and", "OR": "or", "NOT": "not", "XOR": "xor", "And": "and", "Or": "or", "Not": "not",
    "NULL": "null", "Nil": "nil", "TO": "to",
}
_UNWRAP = {
    "textbf", "textit", "emph", "texttt", "textrm", "textsf", "textsc", "textnormal", "text", "mbox",
    "FuncSty", "KwSty", "ArgSty", "DataSty", "CommentSty", "ProgSty", "underline",
}
_SPACES = {",", ";", ":", "!", " ", "quad", "qquad", "enspace", "thinspace"}
_MATH_RE = re.compile(r"\$\$.*?\$\$|\$(?:\\.|[^$\\])*\$|\\\(.*?\\\)", re.DOTALL)


def _clean_text(text: str, on_label: Callable[[str], None]) -> str:
    out: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char == "\\":
            match = re.match(r"\\([A-Za-z]+)\*?|\\(.)", text[i:], re.DOTALL)
            if not match:
                i += 1
                continue
            name = match.group(1)
            i += match.end()
            if name is None:
                symbol = match.group(2)
                out.append(" " if symbol in _SPACES or symbol == "\\" else symbol)
                continue
            if name == "label":
                group = read_group(text, i)
                if group:
                    on_label(group[0].strip())
                    i = group[1]
                continue
            if name in _INLINE_WORDS:
                out.append(_INLINE_WORDS[name])
                continue
            if name in _SPACES:
                out.append(" ")
                continue
            out.append("\\" + name)
            continue
        if char in "{}":
            i += 1
            continue
        out.append(" " if char in "~\n\t" else char)
        i += 1
    return "".join(out)


def _unwrap_commands(text: str) -> str:
    """``\\Call{f}{x}`` -> ``f(x)`` and ``\\textbf{x}`` -> ``x``, outside math.

    Done before math is split out, because arguments often contain math.
    """
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "$" or text.startswith("\\(", i):
            match = _MATH_RE.match(text, i)
            end = match.end() if match else i + 1
            out.append(text[i:end])
            i = end
            continue
        match = re.match(r"\\([A-Za-z]+)", text[i:])
        if match and (match.group(1) == "Call" or match.group(1) in _UNWRAP):
            first = read_group(text, i + match.end())
            if first and match.group(1) == "Call":
                second = read_group(text, first[1])
                if second:
                    out.append(f"{_unwrap_commands(first[0])}({_unwrap_commands(second[0])})")
                    i = second[1]
                    continue
            elif first:
                out.append(_unwrap_commands(first[0]))
                i = first[1]
                continue
        if text[i] == "\\":
            out.append(text[i : i + 2])
            i += 2
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _clean(text: str, on_label: Callable[[str], None]) -> str:
    """Inline LaTeX -> plain text, keeping math as ``$...$``."""
    text = _unwrap_commands(text)
    pieces: list[str] = []
    last = 0
    for match in _MATH_RE.finditer(text):
        pieces.append(_clean_text(text[last : match.start()], on_label))
        math = match.group(0)
        if math.startswith("\\("):
            math = "$" + math[2:-2] + "$"
        pieces.append(re.sub(r"\\label\s*\{[^{}]*\}", "", math))
        last = match.end()
    pieces.append(_clean_text(text[last:], on_label))
    return re.sub(r"\s+", " ", "".join(pieces)).strip()


class _Lines:
    """Collects (indent, text, numbered) lines and their labels."""

    def __init__(self, numbered: bool, on_label: LabelSink) -> None:
        self.numbered = numbered
        self.on_label = on_label
        self.lines: list[tuple[int, str, bool]] = []
        self.count = 0

    def emit(self, indent: int, raw: str, *, numbered: bool = True) -> None:
        labels: list[str] = []
        text = _clean(raw, labels.append)
        if not text:
            # A label on its own (after \\For{...}) belongs to the line before.
            for label in labels:
                self.on_label(label, str(self.count))
            return
        numbered = numbered and self.numbered
        if numbered:
            self.count += 1
            for label in labels:
                self.on_label(label, str(self.count))
        self.lines.append((max(indent, 0), text, numbered))

    def render(self) -> str:
        width = len(str(self.count))
        out: list[str] = []
        number = 0
        for indent, text, numbered in self.lines:
            prefix = ""
            if self.numbered:
                if numbered:
                    number += 1
                    prefix = f"{number:>{width}}: "
                else:
                    prefix = " " * (width + 2)
            out.append((prefix + INDENT * indent + text).rstrip())
        return "\n".join(out)


def format_algorithmic(body: str, *, numbered: bool = False, on_label: LabelSink = lambda *_: None) -> str:
    """Format an ``algorithmic`` (algpseudocode or algorithmic) body."""
    lines = _Lines(numbered, on_label)
    indent = 0
    current: list[str] | None = None
    current_numbered = True
    current_indent = 0

    def flush() -> None:
        nonlocal current
        if current is not None:
            lines.emit(current_indent, "".join(current), numbered=current_numbered)
        current = None

    def start(*, numbered_line: bool, prefix: str = "") -> None:
        nonlocal current, current_numbered, current_indent
        flush()
        current, current_numbered, current_indent = [prefix], numbered_line, indent

    i = 0
    while i < len(body):
        char = body[i]
        if char == "$":
            match = _MATH_RE.match(body, i)
            end = match.end() if match else i + 1
            if current is None:
                start(numbered_line=False)
            current.append(body[i:end])
            i = end
            continue
        if char == "\\":
            match = re.match(r"\\([A-Za-z]+)", body[i:])
            name = match.group(1) if match else ""
            canonical = name if name in _ALGX else _ALGORITHMIC.get(name)
            if canonical:
                count, role, template = _ALGX[canonical]
                j = i + len(name) + 1
                if role != "comment":  # \Comment{} and \COMMENT{} take no optional argument
                    optional = read_optional(body, j)
                    if optional and canonical in ("If", "For", "While", "ElsIf", "ForAll", "Until", "State"):
                        j = optional[1]
                args: list[str] = []
                for _ in range(count):
                    group = read_group(body, j)
                    if group is None:
                        break
                    args.append(group[0])
                    j = group[1]
                i = j
                text = template.format(*args) if args or "{" not in template else template
                if role == "stmt":
                    start(numbered_line=True, prefix=text + " " if text else "")
                elif role == "stmtx":
                    start(numbered_line=False)
                elif role == "head":
                    start(numbered_line=False, prefix=text + " ")
                elif role == "open":
                    flush()
                    lines.emit(indent, text)
                    indent += 1
                elif role == "mid":
                    flush()
                    lines.emit(indent - 1, text)
                elif role == "close":
                    flush()
                    indent -= 1
                    lines.emit(indent, text)
                elif role == "return":
                    if current is None or not "".join(current).strip():
                        start(numbered_line=True, prefix="return ")
                    else:
                        current.append(" return ")
                elif role == "comment":
                    comment = f" ▷ {args[0] if args else ''}"
                    if current is None:
                        start(numbered_line=False)
                    current.append(comment)
                continue
            if current is None and name:
                start(numbered_line=False)
            end = i + (len(name) + 1 if name else 2)
            if current is not None:
                current.append(body[i:end])
            i = end
            continue
        if current is None:
            if char.isspace():
                i += 1
                continue
            start(numbered_line=False)
        current.append(char)
        i += 1
    flush()
    return lines.render()


# algorithm2e: name -> (argument count, header template, closing line or None, takes body)
_A2E_BLOCKS: dict[str, tuple[int, str, str | None]] = {
    "If": (2, "if {0} then", "end"),
    "uIf": (2, "if {0} then", None),
    "ElseIf": (2, "else if {0} then", "end"),
    "uElseIf": (2, "else if {0} then", None),
    "Else": (1, "else", "end"),
    "uElse": (1, "else", None),
    "eIf": (3, "if {0} then", "end"),
    "For": (2, "for {0} do", "end"),
    "ForEach": (2, "foreach {0} do", "end"),
    "ForAll": (2, "forall {0} do", "end"),
    "While": (2, "while {0} do", "end"),
    "Repeat": (2, "repeat", "until {0}"),
    "Begin": (1, "begin", "end"),
    "Fn": (2, "function {0}", "end"),
    "Proc": (2, "procedure {0}", "end"),
    "Prog": (2, "{0}", "end"),
    "Switch": (2, "switch {0} do", "end"),
    "Case": (2, "case {0} do", "end"),
    "Other": (1, "otherwise do", "end"),
}
_A2E_LINE_BLOCKS = {"lIf": "if {0} then", "lElseIf": "else if {0} then", "lElse": "else", "lFor": "for {0} do",
                    "lForEach": "foreach {0} do", "lForAll": "forall {0} do", "lWhile": "while {0} do",
                    "lRepeat": "repeat", "lCase": "case {0}", "lOther": "otherwise"}
_A2E_KEYWORDS = {"KwIn": "Input:", "KwOut": "Output:", "KwData": "Data:", "KwResult": "Result:"}
_A2E_IGNORE = {
    "SetAlgoLined": 0, "DontPrintSemicolon": 0, "PrintSemicolon": 0, "LinesNumbered": 0, "LinesNotNumbered": 0,
    "SetAlgoNoLine": 0, "SetAlgoNoEnd": 0, "SetAlgoVlined": 0, "BlankLine": 0, "Indm": 0, "Indp": 0,
    "nl": 0, "SetKwInOut": 2, "SetKwInput": 2, "SetKwFunction": 2, "SetKwProg": 4, "SetKw": 2, "SetKwData": 2,
    "SetKwBlock": 3, "SetNlSty": 3, "IncMargin": 1, "DecMargin": 1, "SetAlgoCaptionSeparator": 1,
    "SetKwRepeat": 3, "SetKwIF": 6, "SetKwFor": 4, "SetKwSwitch": 7, "SetAlCapFnt": 1, "SetAlCapNameFnt": 1,
    "caption": 1, "label": 1, "AlgoDontDisplayBlockMarkers": 0, "SetAlgoSkip": 1, "SetInd": 2,
}


def _a2e_definitions(body: str) -> tuple[dict[str, str], dict[str, str]]:
    """Names declared with \\SetKwFunction and \\SetKwInOut/\\SetKwInput."""
    functions = dict(re.findall(r"\\SetKw(?:Function|Data)\s*\{\\?(\w+)\}\s*\{([^{}]*)\}", body))
    inputs = {k: v + ":" for k, v in re.findall(r"\\SetKwIn(?:Out|put)\s*\{\\?(\w+)\}\s*\{([^{}]*)\}", body)}
    return functions, inputs


def format_algorithm2e(body: str, *, on_label: LabelSink = lambda *_: None) -> str:
    """Format the body of an ``algorithm2e`` ``algorithm`` environment."""
    functions, inputs = _a2e_definitions(body)
    lines = _Lines(False, on_label)

    def walk(text: str, indent: int) -> None:
        buffer: list[str] = []

        def flush() -> None:
            lines.emit(indent, "".join(buffer))
            buffer.clear()

        i = 0
        while i < len(text):
            char = text[i]
            if char == "$":
                match = _MATH_RE.match(text, i)
                end = match.end() if match else i + 1
                buffer.append(text[i:end])
                i = end
                continue
            if char != "\\":
                buffer.append(char)
                i += 1
                continue
            if text.startswith("\\;", i):
                flush()
                i += 2
                continue
            match = re.match(r"\\([A-Za-z]+)(\*?)", text[i:])
            if not match:
                buffer.append(text[i : i + 2])
                i += 2
                continue
            name = match.group(1)
            j = i + match.end()

            def args(count: int, start: int) -> tuple[list[str], int]:
                found: list[str] = []
                position = start
                optional = read_optional(text, position)
                if optional:
                    position = optional[1]
                for _ in range(count):
                    group = read_group(text, position)
                    if group is None:
                        break
                    found.append(group[0])
                    position = group[1]
                return found, position

            if name in _A2E_BLOCKS:
                count, header, closing = _A2E_BLOCKS[name]
                found, i = args(count, j)
                flush()
                condition = found[0] if count > 1 and found else ""
                lines.emit(indent, header.format(condition))
                if name == "eIf" and len(found) == 3:
                    walk(found[1], indent + 1)
                    lines.emit(indent, "else")
                    walk(found[2], indent + 1)
                elif found:
                    walk(found[-1], indent + 1)
                if closing:
                    lines.emit(indent, closing.format(condition))
                continue
            if name in _A2E_LINE_BLOCKS:
                header = _A2E_LINE_BLOCKS[name]
                count = 1 if "{0}" not in header else 2
                found, i = args(count, j)
                flush()
                condition = found[0] if count == 2 and found else ""
                statement = found[-1] if found else ""
                lines.emit(indent, f"{header.format(condition)} {statement}")
                continue
            if name in _A2E_KEYWORDS or name in inputs:
                found, i = args(1, j)
                flush()
                keyword = _A2E_KEYWORDS.get(name) or inputs[name]
                lines.emit(indent, f"{keyword} {found[0] if found else ''}", numbered=False)
                continue
            if name in ("KwRet", "Return"):
                found, i = args(1, j)
                buffer.append(f"return {found[0] if found else ''}")
                continue
            if name in ("tcp", "tcc", "tcpa", "tccc"):
                found, i = args(1, j)
                comment = f"// {found[0] if found else ''}"
                if "".join(buffer).strip():
                    buffer.append(f" {comment}")
                else:
                    lines.emit(indent, comment, numbered=False)
                continue
            if name in functions:
                found, i = args(1, j)
                buffer.append(f"{functions[name]}({found[0] if found else ''})")
                continue
            if name in _A2E_IGNORE:
                _, i = args(_A2E_IGNORE[name], j)
                continue
            buffer.append(text[i:j])
            i = j
        flush()

    walk(body, 0)
    return lines.render()


def looks_like_algorithm2e(body: str) -> bool:
    return "\\begin{algorithmic" not in body and bool(
        re.search(r"\\;|\\Kw(?:In|Out|Data|Result|Ret)\b|\\(?:SetAlgoLined|DontPrintSemicolon|eIf|uIf|tcp)\b", body)
    )


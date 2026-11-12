"""Decide which images Markdown -> LaTeX output may reference.

``\\includegraphics{/etc/passwd}`` or ``{../../secret.png}`` in generated
LaTeX makes whoever compiles it read files outside the project, and remote
URLs cannot be compiled at all. Images are checked on pandoc's JSON AST
(in Python, where paths can be resolved properly): ``data:`` URIs stay, local
paths stay only inside ``resource_dir`` (or, without one, when they are
relative and do not climb out with ``..``), ``http(s)`` stays only when
remote images are allowed. Everything else is replaced by its alt text and
reported as a ``dropped_image`` warning.
"""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import unquote

from latex2md.result import ConversionWarning

_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):")


def image_problem(url: str, *, resource_dir: Path | None, allow_remote: bool) -> str | None:
    """Why ``url`` may not be referenced, or None when it is fine."""
    scheme = _SCHEME_RE.match(url)
    if scheme and len(scheme.group(1)) > 1:  # "C:" is a Windows drive, not a scheme
        name = scheme.group(1).lower()
        if name == "data":
            return None
        if name in ("http", "https"):
            return None if allow_remote else "remote image (allow_remote_images=False)"
        return f"unsupported URL scheme {name!r}"
    path_text = unquote(url.split("#", 1)[0].split("?", 1)[0])
    if not path_text:
        return "empty path"
    windows = PureWindowsPath(path_text)
    absolute = PurePosixPath(path_text).is_absolute() or bool(windows.drive) or path_text.startswith("~")
    if resource_dir is None:
        if absolute:
            return "absolute path"
        if ".." in PurePosixPath(path_text.replace("\\", "/")).parts:
            return "path outside the document folder"
        return None
    root = resource_dir.resolve()
    candidate = Path(path_text) if absolute else root / path_text
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError):
        return "unresolvable path"
    if not resolved.is_relative_to(root):
        return "outside resource_dir"
    if not resolved.is_file():
        return "missing from resource_dir"
    return None


def _plain_inlines(blocks: list[dict[str, Any]]) -> list[Any]:
    inlines: list[Any] = []
    for block in blocks:
        if block.get("t") in ("Plain", "Para"):
            if inlines:
                inlines.append({"t": "Space"})
            inlines.extend(block.get("c", []))
    return inlines


def _contains_image(node: Any) -> bool:
    if isinstance(node, dict):
        return node.get("t") == "Image" or any(_contains_image(value) for value in node.values())
    if isinstance(node, list):
        return any(_contains_image(item) for item in node)
    return False


def filter_images(
    ast: dict[str, Any], *, resource_dir: Path | None, allow_remote: bool
) -> list[ConversionWarning]:
    """Drop disallowed images from ``ast`` in place; return the warnings."""
    warnings: list[ConversionWarning] = []

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            out: list[Any] = []
            for item in node:
                if isinstance(item, dict) and item.get("t") == "Image":
                    _, alt, (url, _title) = item["c"]
                    problem = image_problem(url, resource_dir=resource_dir, allow_remote=allow_remote)
                    if problem:
                        warnings.append(ConversionWarning("dropped_image", f"{url}: {problem}"))
                        out.extend(walk(alt))
                        continue
                out.append(walk(item))
            return out
        if isinstance(node, dict):
            if node.get("t") == "Figure":
                attr, caption, content = node["c"]
                content = walk(content)
                caption = walk(caption)
                if not _contains_image(content):
                    # Nothing left to show: keep the caption as a paragraph.
                    inlines = _plain_inlines(caption[1])
                    return {"t": "Div", "c": [["", [], []], [{"t": "Para", "c": inlines}] if inlines else []]}
                return {"t": "Figure", "c": [attr, caption, content]}
            return {key: walk(value) for key, value in node.items()}
        return node

    ast["blocks"] = walk(ast["blocks"])
    return warnings


def references_as_list(ast: dict[str, Any]) -> None:
    """citeproc's ``Div#refs`` -> unnumbered "References" heading + bullet list.

    pandoc writes it as a ``CSLReferences`` environment, which only pandoc's
    own template defines, so fragments get ordinary LaTeX instead.
    """
    blocks = []
    for block in ast["blocks"]:
        if block.get("t") == "Div" and block["c"][0][0] == "refs":
            items = []
            for entry in block["c"][1]:
                entry_blocks = entry["c"][1] if entry.get("t") == "Div" else [entry]
                items.append([{"t": "Plain", "c": _plain_inlines(entry_blocks)}])
            blocks.append({"t": "Header", "c": [1, ["", ["unnumbered"], []], [{"t": "Str", "c": "References"}]]})
            if items:
                blocks.append({"t": "BulletList", "c": items})
            continue
        blocks.append(block)
    ast["blocks"] = blocks

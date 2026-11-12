"""Conversion results that carry warnings next to the text.

Silent data loss is the worst failure mode of a converter: an include that was
skipped or a command pandoc did not know simply vanishes from the output. The
``convert_*`` functions therefore return the text together with a list of
:class:`ConversionWarning`, so callers can surface or reject lossy conversions
(the CLI's ``--strict``).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Kinds a caller can match on. "pandoc" is the catch-all for other pandoc warnings.
WARNING_KINDS = (
    "skipped_include",
    "unknown_command",
    "unknown_environment",
    "missing_bibliography",
    "bibliography",
    "unresolved_reference",
    "dropped_image",
    "pandoc",
)


@dataclass(frozen=True)
class ConversionWarning:
    """Something the conversion could not carry over faithfully."""

    kind: str
    message: str
    location: str | None = None

    def __str__(self) -> str:
        where = f" ({self.location})" if self.location else ""
        return f"{self.kind}: {self.message}{where}"


@dataclass
class ConversionResult:
    """Converted ``text`` plus the ``warnings`` raised while producing it."""

    text: str
    warnings: list[ConversionWarning] = field(default_factory=list)

    def __str__(self) -> str:
        return self.text


class WarningLog(list[ConversionWarning]):
    """A list of warnings that ignores exact duplicates.

    One unknown macro used fifty times should be one warning, not fifty.
    """

    def add(self, kind: str, message: str, location: str | None = None) -> None:
        warning = ConversionWarning(kind, message, location)
        if not any(w.kind == kind and w.message == message for w in self):
            self.append(warning)

    def extend_unique(self, warnings: list[ConversionWarning]) -> None:
        for warning in warnings:
            self.add(warning.kind, warning.message, warning.location)

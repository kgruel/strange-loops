"""Facet: the atomic measurable face of a shape."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Facet:
    """A named, typed face of a shape.

    Attributes:
        name: The facet identifier.
        kind: The type name (str, int, float, bool, dict, list, set, datetime).
        optional: Whether the facet may be absent.
    """

    name: str
    kind: str  # str, int, float, bool, dict, list, set, datetime
    optional: bool = False

    @classmethod
    def from_type_str(cls, name: str, type_str: str) -> Facet:
        """Parse a type string like 'int?' into a Facet.

        The trailing '?' indicates an optional facet.
        """
        if type_str.endswith("?"):
            return cls(name=name, kind=type_str[:-1], optional=True)
        return cls(name=name, kind=type_str, optional=False)

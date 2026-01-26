"""Field: the atomic unit of form structure."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    """A typed slot in a shape. The atomic unit of form structure.

    Attributes:
        name: The field identifier.
        kind: The type name (str, int, float, bool, dict, list, set, datetime).
        optional: Whether the field may be absent.
    """

    name: str
    kind: str  # str, int, float, bool, dict, list, set, datetime
    optional: bool = False

    @classmethod
    def from_type_str(cls, name: str, type_str: str) -> Field:
        """Parse a type string like 'int?' into a Field.

        The trailing '?' indicates an optional field.
        """
        if type_str.endswith("?"):
            return cls(name=name, kind=type_str[:-1], optional=True)
        return cls(name=name, kind=type_str, optional=False)

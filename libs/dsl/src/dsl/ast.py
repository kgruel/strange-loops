"""AST types for .loop and .vertex DSL files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


# -----------------------------------------------------------------------------
# Duration
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Duration:
    """Time duration (e.g., 5s, 1m, 500ms)."""

    milliseconds: int

    @classmethod
    def parse(cls, s: str) -> Duration:
        """Parse Go-style duration: 5s, 1m, 500ms, 1h30m."""
        total_ms = 0
        current = ""
        i = 0
        while i < len(s):
            c = s[i]
            if c.isdigit():
                current += c
                i += 1
            elif c == "h":
                total_ms += int(current) * 3600 * 1000
                current = ""
                i += 1
            elif c == "m" and i + 1 < len(s) and s[i + 1] == "s":
                total_ms += int(current)
                current = ""
                i += 2
            elif c == "m":
                total_ms += int(current) * 60 * 1000
                current = ""
                i += 1
            elif c == "s":
                total_ms += int(current) * 1000
                current = ""
                i += 1
            else:
                raise ValueError(f"Invalid duration character: {c}")
        if current:
            raise ValueError(f"Trailing number without unit: {current}")
        return cls(milliseconds=total_ms)

    def seconds(self) -> float:
        """Return duration in seconds."""
        return self.milliseconds / 1000

    def __str__(self) -> str:
        ms = self.milliseconds
        parts = []
        if ms >= 3600000:
            parts.append(f"{ms // 3600000}h")
            ms %= 3600000
        if ms >= 60000:
            parts.append(f"{ms // 60000}m")
            ms %= 60000
        if ms >= 1000:
            parts.append(f"{ms // 1000}s")
            ms %= 1000
        if ms > 0:
            parts.append(f"{ms}ms")
        return "".join(parts) if parts else "0s"


# -----------------------------------------------------------------------------
# Parse Steps (for .loop files)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Skip:
    """Filter out lines matching regex."""

    pattern: str


@dataclass(frozen=True)
class Split:
    """Divide line into fields."""

    delimiter: str | None = None  # None = whitespace


@dataclass(frozen=True)
class Pick:
    """Select fields by index, optionally rename."""

    indices: tuple[int, ...]
    names: tuple[str, ...] | None = None  # If provided, must match indices length


@dataclass(frozen=True)
class Transform:
    """Apply transformations to a named field."""

    field: str
    operations: tuple[TransformOp, ...]


# Transform operations
@dataclass(frozen=True)
class Strip:
    """Remove characters from both ends."""

    chars: str


@dataclass(frozen=True)
class LStrip:
    """Remove characters from left."""

    chars: str


@dataclass(frozen=True)
class RStrip:
    """Remove characters from right."""

    chars: str


@dataclass(frozen=True)
class Replace:
    """Replace substring."""

    old: str
    new: str


@dataclass(frozen=True)
class Coerce:
    """Type coercion."""

    type: Literal["int", "float", "bool", "str"]


TransformOp = Strip | LStrip | RStrip | Replace | Coerce
ParseStep = Skip | Split | Pick | Transform


# -----------------------------------------------------------------------------
# Trigger (for .loop files - Cadence/Source split)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Trigger:
    """Event trigger for a loop.

    Single kind or list of kinds (OR semantics).
    Specifies when a loop should execute.
    """

    kinds: tuple[str, ...]

    @classmethod
    def single(cls, kind: str) -> "Trigger":
        """Create trigger for single kind."""
        return cls((kind,))

    @classmethod
    def multi(cls, kinds: list[str]) -> "Trigger":
        """Create trigger for multiple kinds (OR semantics)."""
        return cls(tuple(kinds))


# -----------------------------------------------------------------------------
# Fold Operations (for .vertex files)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class FoldBy:
    """Dict keyed by field, upsert per fact."""

    key_field: str


@dataclass(frozen=True)
class FoldCount:
    """Increment counter by 1."""

    pass


@dataclass(frozen=True)
class FoldSum:
    """Sum values of a field."""

    field: str


@dataclass(frozen=True)
class FoldLatest:
    """Most recent timestamp."""

    pass


@dataclass(frozen=True)
class FoldCollect:
    """Keep last N items."""

    max_items: int


@dataclass(frozen=True)
class FoldMax:
    """Track maximum value."""

    field: str


@dataclass(frozen=True)
class FoldMin:
    """Track minimum value."""

    field: str


@dataclass(frozen=True)
class FoldAvg:
    """Running average of a field."""

    field: str


@dataclass(frozen=True)
class FoldWindow:
    """Sliding window buffer."""

    field: str
    size: int


FoldOp = FoldBy | FoldCount | FoldSum | FoldLatest | FoldCollect | FoldMax | FoldMin | FoldAvg | FoldWindow


@dataclass(frozen=True)
class FoldDecl:
    """A fold declaration: target field and operation."""

    target: str
    op: FoldOp


# -----------------------------------------------------------------------------
# Boundary (for .vertex files)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class BoundaryWhen:
    """Kind-based boundary: triggers when fact of given kind arrives."""

    kind: str


@dataclass(frozen=True)
class BoundaryAfter:
    """Count-based boundary: fire after N facts (one-shot)."""

    count: int


@dataclass(frozen=True)
class BoundaryEvery:
    """Count-based boundary: fire every N facts (repeating)."""

    count: int


Boundary = BoundaryWhen | BoundaryAfter | BoundaryEvery


# -----------------------------------------------------------------------------
# Loop Definition (within .vertex)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class LoopDef:
    """Loop definition within a .vertex file."""

    folds: tuple[FoldDecl, ...]
    boundary: Boundary | None = None


# -----------------------------------------------------------------------------
# Top-level File ASTs
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class LoopFile:
    """AST for a .loop file."""

    kind: str
    observer: str
    source: str | None = None  # Optional for pure timer loops
    every: Duration | None = None
    on: Trigger | None = None  # Event trigger (mutually exclusive with every)
    format: Literal["lines", "json", "blob"] = "lines"
    timeout: Duration = Duration(60000)  # 60s default
    env: dict[str, str] | None = None
    parse: tuple[ParseStep, ...] = ()

    # Source location for error reporting
    path: Path | None = None


@dataclass(frozen=True)
class VertexFile:
    """AST for a .vertex file."""

    name: str
    loops: dict[str, LoopDef]
    store: Path | None = None
    discover: str | None = None
    sources: tuple[Path, ...] | None = None
    vertices: tuple[Path, ...] | None = None
    routes: dict[str, str] | None = None
    emit: str | None = None

    # Source location for error reporting
    path: Path | None = None

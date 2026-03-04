"""AST types for .loop and .vertex DSL files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
class Select:
    """Select specific fields from a dict (for ndjson format)."""

    fields: tuple[str, ...]


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


@dataclass(frozen=True)
class Explode:
    """Fan-out: evaluate path on record, produce N output records."""

    path: str
    carry: dict[str, str] | None = None


@dataclass(frozen=True)
class Project:
    """Field mapping with nested JSON paths."""

    fields: dict[str, str]


@dataclass(frozen=True)
class Where:
    """Record filter by field value comparison."""

    path: str
    op: str = "equals"
    value: str | None = None


ParseStep = Skip | Split | Pick | Select | Transform | Explode | Project | Where


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
    search: tuple[str, ...] = ()  # payload field names for FTS5 indexing


# -----------------------------------------------------------------------------
# Source Templates (for parameterized sources)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceParams:
    """One row of template parameters."""

    values: dict[str, str]


# -----------------------------------------------------------------------------
# External parameter sources (for template sources)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class FromFile:
    """Parameters sourced from an external file."""

    path: Path


FromSource = FromFile


@dataclass(frozen=True)
class TemplateSource:
    """A source template with instantiation parameters and loop spec.

    template: Path to the .loop template file
    params: Tuple of parameter rows, each row instantiates the template once
    from_: Optional external parameter source (e.g., FromFile)
    loop: Optional LoopDef (fold + boundary) applied to all instances
    """

    template: Path
    params: tuple[SourceParams, ...]
    from_: FromSource | None = None
    loop: "LoopDef | None" = None


# Union type for sources: entries
SourceEntry = Path | TemplateSource


# -----------------------------------------------------------------------------
# Inline Sources (for sources blocks with execution mode)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class InlineSource:
    """An inline source definition within a sources block.

    Minimal source spec: command + kind. Observer defaults to vertex name
    at compile time.
    """

    command: str
    kind: str


@dataclass(frozen=True)
class SourcesBlock:
    """A sources block with execution mode.

    Wraps inline source definitions with an execution mode keyword.
    'sequential' runs sources in declaration order with exit-on-failure gating.
    """

    mode: str  # "sequential"
    sources: tuple[InlineSource, ...]


# -----------------------------------------------------------------------------
# Combine Entry (for combinatorial vertices)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class CombineEntry:
    """A vertex reference in a combine block."""

    name: str  # vertex name (resolved via resolve_vertex)


# -----------------------------------------------------------------------------
# Observer Declaration (for .vertex files)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class GrantDecl:
    """Grant constraints for an observer."""

    potential: frozenset[str]  # kinds this observer can emit


@dataclass(frozen=True)
class ObserverDecl:
    """An observer declared in a vertex file."""

    name: str
    identity: str | None = None  # vertex name for identity store
    grant: GrantDecl | None = None  # emission constraints


# -----------------------------------------------------------------------------
# Top-level File ASTs
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class LoopFile:
    """AST for a .loop file."""

    kind: str
    observer: str
    source: str | None = None  # Optional for pure timer loops
    every: str | None = None
    on: Trigger | None = None  # Event trigger (mutually exclusive with every)
    format: str = "lines"
    timeout: str = "60s"
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
    sources: tuple[SourceEntry, ...] | None = None
    vertices: tuple[Path, ...] | None = None
    routes: dict[str, str] | None = None
    emit: str | None = None
    combine: tuple[CombineEntry, ...] | None = None
    sources_blocks: tuple[SourcesBlock, ...] | None = None
    observers: tuple[ObserverDecl, ...] | None = None

    # Source location for error reporting
    path: Path | None = None

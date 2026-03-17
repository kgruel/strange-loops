"""AST types for .loop and .vertex DSL files."""

from __future__ import annotations

# pathlib deferred — Path only used in annotations (strings with __future__)


_setattr = object.__setattr__


def _frozen(cls):
    """Minimal frozen-dataclass decorator — avoids importing dataclasses (~12ms).

    Generates __init__, __repr__, __eq__, __hash__ for classes with
    __annotations__. Fields with class-level defaults are optional in __init__.
    ClassVar annotations are excluded from instance fields.
    """
    annotations = {}
    for klass in reversed(cls.__mro__):
        annotations.update(getattr(klass, '__annotations__', {}))
    # Filter out ClassVar fields
    fields = tuple(
        name for name, ann in annotations.items()
        if not (isinstance(ann, str) and 'ClassVar' in ann)
    )
    defaults = {}
    for f in fields:
        if hasattr(cls, f):
            val = getattr(cls, f)
            if not callable(val) or isinstance(val, (type, frozenset)):
                defaults[f] = val

    has_post_init = hasattr(cls, '__post_init__')
    post_init = cls.__post_init__ if has_post_init else None

    # Build __init__ via closure (avoids exec overhead at import time).
    # Uses *args/**kwargs dispatch — slightly slower per-call than exec'd
    # positional params, but saves ~1.3ms at import for 42 classes.
    n_req = len(fields) - len(defaults)
    _req = fields[:n_req]
    _opt = fields[n_req:]
    _defs = defaults
    _pi = post_init
    _n_fields = len(fields)

    def __init__(self, *args, **kwargs):
        i = 0
        for f in _req:
            if i < len(args):
                _setattr(self, f, args[i]); i += 1
            elif f in kwargs:
                _setattr(self, f, kwargs[f])
            else:
                raise TypeError(f'{cls.__name__}() missing required argument: {f!r}')
        for f in _opt:
            if i < len(args):
                _setattr(self, f, args[i]); i += 1
            elif f in kwargs:
                _setattr(self, f, kwargs[f])
            else:
                _setattr(self, f, _defs[f])
        if _pi:
            _pi(self)

    cls.__init__ = __init__

    # Frozen
    cls.__setattr__ = _frozen_setattr
    cls.__delattr__ = _frozen_delattr

    # __eq__ / __hash__
    cls.__eq__ = lambda self, other: (
        tuple(getattr(self, f) for f in fields) == tuple(getattr(other, f) for f in fields)
        if type(self) is type(other) else NotImplemented
    )
    cls.__hash__ = lambda self: hash(tuple(getattr(self, f) for f in fields))

    # __repr__ via closure (avoids exec)
    _name = cls.__name__
    _fields = fields
    def __repr__(self, _n=_name, _f=_fields):
        parts = ', '.join(f'{f}={getattr(self, f)!r}' for f in _f)
        return f'{_n}({parts})'
    cls.__repr__ = __repr__

    cls.__match_args__ = fields

    # Clean up class-level defaults
    for f in defaults:
        try:
            delattr(cls, f)
        except AttributeError:
            pass

    # Rebuild class with real __slots__ (like dataclasses slots=True)
    # This makes instances use slot descriptors instead of __dict__
    qualname = cls.__qualname__
    new_cls = type(cls)(cls.__name__, cls.__bases__, {
        **{k: v for k, v in cls.__dict__.items() if k != '__dict__'},
        '__slots__': fields,
    })
    new_cls.__qualname__ = qualname
    new_cls.__module__ = cls.__module__
    return new_cls


def _frozen_setattr(self, name, value):
    raise AttributeError(f"cannot assign to field '{name}'")

def _frozen_delattr(self, name):
    raise AttributeError(f"cannot delete field '{name}'")


def dataclass(frozen=True):
    """Drop-in replacement for @dataclass(frozen=True) without importing dataclasses."""
    assert frozen, "Only frozen=True is supported"
    return _frozen


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
    values: tuple[str, ...] = ()


@dataclass(frozen=True)
class Flatten:
    """Flatten an array-of-objects field into a searchable text field.

    Takes an array field, extracts named subfields from each element,
    and concatenates into a single text field.
    """

    field: str
    into: str
    extract: tuple[str, ...]


ParseStep = Skip | Split | Pick | Select | Transform | Explode | Project | Where | Flatten


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
class BoundaryCondition:
    """Predicate on fold state — fires when fold target meets condition.

    Evaluated after fold (state is current), against the loop's fold state.
    Match checks payload equality (cheap, string); conditions check fold
    state with comparison operators (numeric).
    """

    target: str          # fold target name (e.g. "high")
    op: str              # ">=", "<=", ">", "<", "==", "!="
    value: float | str   # comparison value

    _VALID_OPS: ClassVar[frozenset[str]] = frozenset({">=", "<=", ">", "<", "==", "!="})

    def __post_init__(self) -> None:
        if self.op not in self._VALID_OPS:
            raise ValueError(f"Invalid condition operator: {self.op!r} (valid: {sorted(self._VALID_OPS)})")


@dataclass(frozen=True)
class BoundaryWhen:
    """Kind-based boundary: triggers when fact of given kind arrives.

    Optional match conditions: payload fields that must equal the given
    values for the boundary to fire. E.g. boundary when="session" status="closed"
    fires only when a session fact has status=closed in its payload.

    Optional fold-state conditions: predicates on fold targets that must
    all be true. E.g. condition "high" ">=" 80 fires only when the "high"
    fold target is >= 80. Evaluated after match passes.

    Optional run clause: shell command to execute when the boundary fires.
    Declared in KDL as a child node: run "scripts/dispatch.sh"
    Engine carries the command on the Tick; app layer executes fire-and-forget.
    """

    kind: str
    match: tuple[tuple[str, str], ...] = ()  # frozen payload conditions
    conditions: tuple[BoundaryCondition, ...] = ()  # fold state predicates
    run: str | None = None  # shell command to execute on fire


@dataclass(frozen=True)
class BoundaryAfter:
    """Count-based boundary: fire after N facts (one-shot)."""

    count: int
    run: str | None = None  # shell command to execute on fire


@dataclass(frozen=True)
class BoundaryEvery:
    """Count-based boundary: fire every N facts (repeating)."""

    count: int
    run: str | None = None  # shell command to execute on fire


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
    parse: tuple[ParseStep, ...] = ()  # per-kind parse pipeline


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
# SourceEntry = Path | TemplateSource  — deferred, only used in annotations


# -----------------------------------------------------------------------------
# Inline Sources (for sources blocks with execution mode)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class InlineSource:
    """An inline source definition within a sources block.

    Shares the full .loop vocabulary with LoopFile. Observer defaults to
    vertex name at compile time (unlike LoopFile which requires explicit).
    """

    command: str
    kind: str
    observer: str = ""
    every: str = ""
    on: Trigger | None = None
    format: str = "lines"
    timeout: str = "60s"
    origin: str = ""
    env: tuple[tuple[str, str], ...] = ()
    parse: tuple[ParseStep, ...] = ()
    path: str = ""


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
    """A vertex reference in a combine block.

    ``alias`` is an optional short name for qualifying reads/emits
    through the parent combine vertex: ``loops read project/alias``.
    When omitted, init derives it from the folder name.
    """

    name: str  # vertex name (resolved via resolve_vertex)
    alias: str | None = None  # short name for slash-qualified access


# -----------------------------------------------------------------------------
# Lens Declaration (for .vertex files)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class LensDecl:
    """Lens declarations for a vertex.

    Names are resolved via search path: vertex-local > project-local > user-global > built-in.
    A name starting with '.' or '/' is treated as a path; otherwise as a search name.
    """

    fold: str | None = None    # lens name/path for fold view
    stream: str | None = None  # lens name/path for stream view


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
    origin: str = ""
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
    lens: LensDecl | None = None
    boundary: Boundary | None = None  # vertex-level boundary (fires all loops)
    observer_scoped: bool = False  # fold defaults to current observer when True

    # Source location for error reporting
    path: Path | None = None

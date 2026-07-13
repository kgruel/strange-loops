"""Declaration document form — AST ↔ per-subject JSON documents (SPEC §9.2).

A ``.vertex`` file's declaration surface is decomposed into **subject-scoped
documents**: each is the *complete current definition* of one subject (a kind,
an observer, a combine member, a source, a lens, or the vertex singleton). No
facet deltas — a mutation re-emits the whole subject document. This is the
document tier the internal-table build (SPEC §9) records as immutable
declaration events under a reserved kind namespace.

This module is pure grammar: it maps between the frozen AST types the parser
returns (``ast.py``) and plain JSON-safe dicts. No engine/atoms/store imports,
no third-party dependencies. Payloads are strictly JSON types (dict/list/str/
int/float/bool/None) so they can later be JCS-canonicalized (rfc8785).

Residence is stripped structurally (SPEC §9.5): the ``store`` locator and the
``VertexFile.path`` NEVER enter documents — they are supplied from outside at
projection time. Observer *public* keys DO enter (meaning-critical, portable);
private-key custody is never in the AST. Host-bound source wiring enters as
``_decl.source-defined`` provenance documents (SPEC §9.2 Ingress stratum).

Union members carry explicit stable type tags (never reflected class names),
so a class rename cannot silently break the wire form. Every union member in
``ast.py`` is enumerated below — folds, boundaries, parse steps, transform ops,
source variants — not sampled.

Forward compatibility is normative: :func:`documents_to_vertex` tolerates
unknown fields inside a document and unknown ``_decl.*`` kinds (skips them),
so a newer protocol's documents project safely under an older reader.

Protocol rules this module enforces (subject identity, ordering, safety):

- **Subject uniqueness.** ``(kind, subject)`` must be unique — the internal
  table's runtime state is a ``Latest`` fold keyed by it (SPEC §9.2), so a
  collision silently drops a subject. Subjects are the human-meaningful base
  (kind name / observer name / member name / source path or command); when two
  documents of one kind would share a base, later occurrences get a
  deterministic ``base#2``, ``base#3`` suffix in encounter order. Suffixes are
  allocated against the *set* of subjects already issued for that kind, not a
  per-base counter — so a suffix never lands on a naturally-occurring subject
  (bases ``["base", "base", "base#2"]`` → ``["base", "base#2", "base#3"]``). The
  suffix is identity only — projection reconstructs every value from the
  *payload*, never by parsing the subject — so a reorder of distinct subjects
  stays stable while identical duplicates disambiguate deterministically.

- **Order is meaning.** Declaration order is load-bearing in this AST
  (sequential source blocks, boundary match "first match fires", kind order
  driving fold/salience rendering) but per-subject ``Latest`` folding erases
  encounter order. So every multi-instance document (kind/observer/member/
  source/lens) carries an integer ``order`` = its encounter position at
  absorption; :func:`documents_to_vertex` restores structure by sorting on
  ``(order, subject)``. A reorder edit re-emits the affected subjects — honest,
  since order *is* meaning where declared. (The vertex-level boundary tuple
  rides ordered inside the vertex-defined singleton and needs no per-doc order.)

- **Source block structure** is recorded on the vertex-defined singleton as a
  ``source_blocks`` list of ``{"index", "mode"}`` (present iff
  ``sources_blocks`` is not None). Inline source documents keep a ``block`` tag;
  projection rebuilds blocks from the singleton list and drops each inline
  source into its block, so block mode and identity are authoritative rather
  than inferred from surviving members.

- **Round-trip guarantee is over loader-reachable ASTs.** The parser structurally
  cannot produce an empty-but-present ``observers=()`` or ``combine=()`` (the
  loader rejects empty ``observers {}`` / ``combine {}`` blocks) or an empty
  ``SourcesBlock`` (empty ``sources sequential {}`` is rejected). These
  empty-present tuples are therefore normalized to ``None`` on projection.
  ``VertexFile.sources`` *is* reachable as an empty tuple (empty ``sources {}``),
  and that distinction is preserved via ``sources_present`` on the singleton.

- **JSON safety is enforced, not assumed.** Every payload is walked at
  serialization (:func:`_ensure_json_safe`): dict keys must be ``str``, values
  must be JSON scalars/lists/dicts, and every float must be finite. A ``NaN`` or
  ``Infinity`` (AST-constructible even though the parser rejects it) or a
  copied-through non-JSON value raises ``ValueError`` with the field path here —
  never later, when JCS canonicalization would be the first to notice.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, NamedTuple

from .ast import (
    BoundaryAfter,
    BoundaryCondition,
    BoundaryEvery,
    BoundaryWhen,
    Coerce,
    CombineEntry,
    EdgeDecl,
    Explode,
    Flatten,
    FoldAvg,
    FoldBy,
    FoldCollect,
    FoldCount,
    FoldDecl,
    FoldLatest,
    FoldMax,
    FoldMin,
    FoldSum,
    FoldWindow,
    FromFile,
    GrantDecl,
    InlineSource,
    LensDecl,
    LoopDef,
    LStrip,
    ObserverDecl,
    Pick,
    Project,
    Replace,
    RStrip,
    Select,
    Skip,
    SourceParams,
    SourcesBlock,
    Split,
    Strip,
    TemplateSource,
    Transform,
    Trigger,
    VertexFile,
    Where,
)

# ---------------------------------------------------------------------------
# Reserved-kind vocabulary (SPEC §9.2, code-frozen)
# ---------------------------------------------------------------------------

DECL_PREFIX = "_decl."

DECL_GENESIS = "_decl.genesis"
DECL_KIND_DEFINED = "_decl.kind-defined"
DECL_KIND_RETIRED = "_decl.kind-retired"
DECL_OBSERVER_DEFINED = "_decl.observer-defined"
DECL_OBSERVER_RETIRED = "_decl.observer-retired"
DECL_MEMBER_DEFINED = "_decl.member-defined"
DECL_MEMBER_REMOVED = "_decl.member-removed"
DECL_VERTEX_DEFINED = "_decl.vertex-defined"
DECL_SOURCE_DEFINED = "_decl.source-defined"
DECL_SOURCE_RETIRED = "_decl.source-retired"
DECL_LENS_DEFINED = "_decl.lens-defined"
DECL_TRANSIT = "_decl.transit"
DECL_MERGED = "_decl.merged"

#: Declaration-protocol version stamped into the genesis payload. A foreign
#: lineage carrying an unsupported version is treated as entirely inert
#: (never partially interpreted) — see SPEC §9.2 / build plan.
DECLARATION_PROTOCOL_VERSION = 1

#: The frozen tombstone vocabulary (SPEC §9.2): which ``*-defined`` kind each
#: subject removal is expressed as. A ``*-defined`` kind ABSENT from this map
#: is a **singleton with no tombstone** — ``_decl.lens-defined`` (spec:
#: "replaced by re-definition") and ``_decl.vertex-defined`` (it IS identity).
#: Removing such a subject is inexpressible in the code-frozen vocabulary; the
#: edit ceremony (S4) refuses it rather than mint a new kind unilaterally
#: (thread:decl-lens-tombstone-vocab-gap — a later coordinated vocab change
#: with the loops-go oracle). This is the single home for the mapping; the
#: engine resolver imports its inverse.
DEFINED_TO_TOMBSTONE: dict[str, str] = {
    DECL_KIND_DEFINED: DECL_KIND_RETIRED,
    DECL_OBSERVER_DEFINED: DECL_OBSERVER_RETIRED,
    DECL_MEMBER_DEFINED: DECL_MEMBER_REMOVED,
    DECL_SOURCE_DEFINED: DECL_SOURCE_RETIRED,
}


def is_internal_kind(kind: str) -> bool:
    """True if ``kind`` is in the reserved declaration namespace (``_decl.*``).

    The single predicate every read/emit/filter site should route through
    (SPEC §9.4 costs; build-plan "SQL wildcard trap"). Dependency-free — a
    plain prefix test — because engine and apps import it directly.
    """
    return kind.startswith(DECL_PREFIX)


class Document(NamedTuple):
    """One subject-scoped declaration document: (kind, subject, payload).

    ``kind`` is a reserved ``_decl.*`` vocabulary constant; ``subject`` is the
    stable identifier of the thing described (kind name, observer name, source
    name, or the vertex name for singletons); ``payload`` is the complete
    current definition as a JSON-safe dict.
    """

    kind: str
    subject: str
    payload: dict[str, Any]

    def as_json(self) -> dict[str, Any]:
        """Flat JSON-safe form: ``{"kind", "subject", "payload"}``."""
        return {"kind": self.kind, "subject": self.subject, "payload": self.payload}


def _ensure_json_safe(obj: Any, path: str) -> None:
    """Assert ``obj`` is strictly JSON-safe, or raise ``ValueError`` with path.

    Enforced at serialization so a bad value (a non-finite float, a non-str
    dict key, a copied-through tuple/set/Path) is caught here — with a field
    path pointing at it — rather than surfacing later at JCS canonicalization.
    ``bool`` is allowed (a JSON scalar); every ``float`` must be finite.
    """
    # bool is an int subclass, so (str, int) already covers True/False.
    if obj is None or isinstance(obj, (str, int)):
        return
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise ValueError(f"non-finite float at {path}: {obj!r}")
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise ValueError(f"non-str dict key at {path}: {k!r}")
            _ensure_json_safe(v, f"{path}.{k}")
        return
    if isinstance(obj, list):
        for i, v in enumerate(obj):
            _ensure_json_safe(v, f"{path}[{i}]")
        return
    raise ValueError(f"non-JSON type {type(obj).__name__} at {path}")


# ===========================================================================
# Union serializers — AST → JSON.  Every member carries an explicit type tag.
# ===========================================================================


def _fold_op_to_json(op: Any) -> dict[str, Any]:
    """FoldOp → ``{"op": <tag>, ...}``. Enumerates all nine members."""
    if isinstance(op, FoldBy):
        return {"op": "by", "key_field": op.key_field}
    if isinstance(op, FoldCount):
        return {"op": "count"}
    if isinstance(op, FoldSum):
        return {"op": "sum", "field": op.field}
    if isinstance(op, FoldLatest):
        return {"op": "latest"}
    if isinstance(op, FoldCollect):
        return {"op": "collect", "max_items": op.max_items}
    if isinstance(op, FoldMax):
        return {"op": "max", "field": op.field}
    if isinstance(op, FoldMin):
        return {"op": "min", "field": op.field}
    if isinstance(op, FoldAvg):
        return {"op": "avg", "field": op.field}
    if isinstance(op, FoldWindow):
        return {"op": "window", "field": op.field, "size": op.size}
    raise TypeError(f"unknown FoldOp member: {type(op).__name__}")


def _fold_op_from_json(d: dict[str, Any]) -> Any:
    tag = d["op"]
    if tag == "by":
        return FoldBy(key_field=d["key_field"])
    if tag == "count":
        return FoldCount()
    if tag == "sum":
        return FoldSum(field=d["field"])
    if tag == "latest":
        return FoldLatest()
    if tag == "collect":
        return FoldCollect(max_items=d["max_items"])
    if tag == "max":
        return FoldMax(field=d["field"])
    if tag == "min":
        return FoldMin(field=d["field"])
    if tag == "avg":
        return FoldAvg(field=d["field"])
    if tag == "window":
        return FoldWindow(field=d["field"], size=d["size"])
    raise ValueError(f"unknown fold op tag: {tag!r}")


def _fold_decl_to_json(decl: FoldDecl) -> dict[str, Any]:
    return {"target": decl.target, "op": _fold_op_to_json(decl.op)}


def _fold_decl_from_json(d: dict[str, Any]) -> FoldDecl:
    return FoldDecl(target=d["target"], op=_fold_op_from_json(d["op"]))


def _transform_op_to_json(op: Any) -> dict[str, Any]:
    """TransformOp → ``{"t": <tag>, ...}``. Enumerates all five members."""
    if isinstance(op, Strip):
        return {"t": "strip", "chars": op.chars}
    if isinstance(op, LStrip):
        return {"t": "lstrip", "chars": op.chars}
    if isinstance(op, RStrip):
        return {"t": "rstrip", "chars": op.chars}
    if isinstance(op, Replace):
        return {"t": "replace", "old": op.old, "new": op.new}
    if isinstance(op, Coerce):
        return {"t": "coerce", "type": op.type}
    raise TypeError(f"unknown TransformOp member: {type(op).__name__}")


def _transform_op_from_json(d: dict[str, Any]) -> Any:
    tag = d["t"]
    if tag == "strip":
        return Strip(chars=d["chars"])
    if tag == "lstrip":
        return LStrip(chars=d["chars"])
    if tag == "rstrip":
        return RStrip(chars=d["chars"])
    if tag == "replace":
        return Replace(old=d["old"], new=d["new"])
    if tag == "coerce":
        return Coerce(type=d["type"])
    raise ValueError(f"unknown transform op tag: {tag!r}")


def _parse_step_to_json(step: Any) -> dict[str, Any]:
    """ParseStep → ``{"step": <tag>, ...}``. Enumerates all nine members."""
    if isinstance(step, Skip):
        return {"step": "skip", "pattern": step.pattern}
    if isinstance(step, Split):
        return {"step": "split", "delimiter": step.delimiter}
    if isinstance(step, Pick):
        return {
            "step": "pick",
            "indices": list(step.indices),
            "names": list(step.names) if step.names is not None else None,
        }
    if isinstance(step, Select):
        return {"step": "select", "fields": list(step.fields)}
    if isinstance(step, Transform):
        return {
            "step": "transform",
            "field": step.field,
            "operations": [_transform_op_to_json(o) for o in step.operations],
        }
    if isinstance(step, Explode):
        return {
            "step": "explode",
            "path": step.path,
            "carry": dict(step.carry) if step.carry is not None else None,
        }
    if isinstance(step, Project):
        return {"step": "project", "fields": dict(step.fields)}
    if isinstance(step, Where):
        return {
            "step": "where",
            "path": step.path,
            "op": step.op,
            "value": step.value,
            "values": list(step.values),
        }
    if isinstance(step, Flatten):
        return {
            "step": "flatten",
            "field": step.field,
            "into": step.into,
            "extract": list(step.extract),
        }
    raise TypeError(f"unknown ParseStep member: {type(step).__name__}")


def _parse_step_from_json(d: dict[str, Any]) -> Any:
    tag = d["step"]
    if tag == "skip":
        return Skip(pattern=d["pattern"])
    if tag == "split":
        return Split(delimiter=d["delimiter"])
    if tag == "pick":
        names = d["names"]
        return Pick(
            indices=tuple(d["indices"]),
            names=tuple(names) if names is not None else None,
        )
    if tag == "select":
        return Select(fields=tuple(d["fields"]))
    if tag == "transform":
        return Transform(
            field=d["field"],
            operations=tuple(_transform_op_from_json(o) for o in d["operations"]),
        )
    if tag == "explode":
        carry = d["carry"]
        return Explode(path=d["path"], carry=dict(carry) if carry is not None else None)
    if tag == "project":
        return Project(fields=dict(d["fields"]))
    if tag == "where":
        return Where(
            path=d["path"],
            op=d.get("op", "equals"),
            value=d.get("value"),
            values=tuple(d.get("values", ())),
        )
    if tag == "flatten":
        return Flatten(field=d["field"], into=d["into"], extract=tuple(d["extract"]))
    raise ValueError(f"unknown parse step tag: {tag!r}")


def _parse_steps_to_json(steps: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [_parse_step_to_json(s) for s in steps]


def _parse_steps_from_json(items: list[dict[str, Any]]) -> tuple[Any, ...]:
    return tuple(_parse_step_from_json(d) for d in items)


def _boundary_condition_to_json(c: BoundaryCondition) -> dict[str, Any]:
    return {"target": c.target, "op": c.op, "value": c.value}


def _boundary_condition_from_json(d: dict[str, Any]) -> BoundaryCondition:
    return BoundaryCondition(target=d["target"], op=d["op"], value=d["value"])


def _boundary_to_json(b: Any) -> dict[str, Any]:
    """Boundary → ``{"type": <tag>, ...}``. Enumerates all three members."""
    if isinstance(b, BoundaryWhen):
        return {
            "type": "when",
            "kind": b.kind,
            "match": [[k, v] for (k, v) in b.match],
            "conditions": [_boundary_condition_to_json(c) for c in b.conditions],
            "run": b.run,
        }
    if isinstance(b, BoundaryAfter):
        return {"type": "after", "count": b.count, "run": b.run}
    if isinstance(b, BoundaryEvery):
        return {"type": "every", "count": b.count, "run": b.run}
    raise TypeError(f"unknown Boundary member: {type(b).__name__}")


def _boundary_from_json(d: dict[str, Any]) -> Any:
    tag = d["type"]
    if tag == "when":
        return BoundaryWhen(
            kind=d["kind"],
            match=tuple((k, v) for k, v in d.get("match", ())),
            conditions=tuple(
                _boundary_condition_from_json(c) for c in d.get("conditions", ())
            ),
            run=d.get("run"),
        )
    if tag == "after":
        return BoundaryAfter(count=d["count"], run=d.get("run"))
    if tag == "every":
        return BoundaryEvery(count=d["count"], run=d.get("run"))
    raise ValueError(f"unknown boundary type tag: {tag!r}")


def _trigger_to_json(t: Trigger | None) -> list[str] | None:
    return list(t.kinds) if t is not None else None


def _trigger_from_json(v: list[str] | None) -> Trigger | None:
    return Trigger(kinds=tuple(v)) if v is not None else None


# ---------------------------------------------------------------------------
# LoopDef  ↔  _decl.kind-defined payload
# ---------------------------------------------------------------------------


def _loop_def_to_payload(loop: LoopDef) -> dict[str, Any]:
    return {
        "folds": [_fold_decl_to_json(f) for f in loop.folds],
        "boundary": _boundary_to_json(loop.boundary)
        if loop.boundary is not None
        else None,
        "search": list(loop.search),
        "parse": _parse_steps_to_json(loop.parse),
        "preview": list(loop.preview_fields),
        "edges": [{"field": e.field, "target": e.target} for e in loop.edges],
    }


def _loop_def_from_payload(p: dict[str, Any]) -> LoopDef:
    boundary = p.get("boundary")
    return LoopDef(
        folds=tuple(_fold_decl_from_json(f) for f in p.get("folds", ())),
        boundary=_boundary_from_json(boundary) if boundary is not None else None,
        search=tuple(p.get("search", ())),
        parse=_parse_steps_from_json(p.get("parse", [])),
        preview_fields=tuple(p.get("preview", ())),
        edges=tuple(
            EdgeDecl(field=e["field"], target=e["target"]) for e in p.get("edges", ())
        ),
    )


# ---------------------------------------------------------------------------
# ObserverDecl  ↔  _decl.observer-defined payload
# ---------------------------------------------------------------------------


def _observer_to_payload(o: ObserverDecl) -> dict[str, Any]:
    grant = (
        {"potential": sorted(o.grant.potential)} if o.grant is not None else None
    )
    return {
        "name": o.name,
        "identity": o.identity,
        "grant": grant,
        "key": o.key,
    }


def _observer_from_payload(p: dict[str, Any]) -> ObserverDecl:
    grant_d = p.get("grant")
    grant = (
        GrantDecl(potential=frozenset(grant_d["potential"]))
        if grant_d is not None
        else None
    )
    return ObserverDecl(
        name=p["name"],
        identity=p.get("identity"),
        grant=grant,
        key=p.get("key"),
    )


# ---------------------------------------------------------------------------
# CombineEntry  ↔  _decl.member-defined payload
# ---------------------------------------------------------------------------


def _combine_to_payload(c: CombineEntry) -> dict[str, Any]:
    return {"name": c.name, "alias": c.alias}


def _combine_from_payload(p: dict[str, Any]) -> CombineEntry:
    return CombineEntry(name=p["name"], alias=p.get("alias"))


# ---------------------------------------------------------------------------
# LensDecl  ↔  _decl.lens-defined payload (whole-vertex singleton)
# ---------------------------------------------------------------------------


def _lens_to_payload(lens: LensDecl) -> dict[str, Any]:
    return {"fold": lens.fold, "stream": lens.stream}


def _lens_from_payload(p: dict[str, Any]) -> LensDecl:
    return LensDecl(fold=p.get("fold"), stream=p.get("stream"))


# ---------------------------------------------------------------------------
# Sources  ↔  _decl.source-defined payloads
#
# Three variants share the source-defined kind, discriminated by "form":
#   - "path":     a bare .loop path entry in VertexFile.sources
#   - "template": a TemplateSource entry in VertexFile.sources
#   - "inline":   an InlineSource inside a VertexFile.sources_blocks group;
#                 carries "block" (group index) + "mode" so the SourcesBlock
#                 grouping and execution mode reconstruct exactly.
#
# Source Paths (host-bound wiring) stay inside these payloads by design —
# this is the Ingress / provenance stratum (SPEC §9.2), not portable config.
# ---------------------------------------------------------------------------


def _source_params_to_json(sp: SourceParams) -> dict[str, Any]:
    return {"values": dict(sp.values)}


def _source_params_from_json(d: dict[str, Any]) -> SourceParams:
    return SourceParams(values=dict(d["values"]))


def _template_source_to_payload(t: TemplateSource) -> dict[str, Any]:
    return {
        "form": "template",
        "template": str(t.template),
        "params": [_source_params_to_json(sp) for sp in t.params],
        "from": {"strategy": "file", "path": str(t.from_.path)}
        if t.from_ is not None
        else None,
        "loop": _loop_def_to_payload(t.loop) if t.loop is not None else None,
    }


def _template_source_from_payload(p: dict[str, Any]) -> TemplateSource:
    from_d = p.get("from")
    loop_d = p.get("loop")
    return TemplateSource(
        template=Path(p["template"]),
        params=tuple(_source_params_from_json(sp) for sp in p.get("params", ())),
        from_=FromFile(path=Path(from_d["path"])) if from_d is not None else None,
        loop=_loop_def_from_payload(loop_d) if loop_d is not None else None,
    )


def _inline_source_to_payload(
    s: InlineSource, *, block: int, mode: str
) -> dict[str, Any]:
    return {
        "form": "inline",
        "block": block,
        "mode": mode,
        "command": s.command,
        "kind": s.kind,
        "observer": s.observer,
        "every": s.every,
        "on": _trigger_to_json(s.on),
        "format": s.format,
        "timeout": s.timeout,
        "origin": s.origin,
        "env": [[k, v] for (k, v) in s.env],
        "parse": _parse_steps_to_json(s.parse),
        "path": s.path,
    }


def _inline_source_from_payload(p: dict[str, Any]) -> InlineSource:
    return InlineSource(
        command=p["command"],
        kind=p["kind"],
        observer=p.get("observer", ""),
        every=p.get("every", ""),
        on=_trigger_from_json(p.get("on")),
        format=p.get("format", "lines"),
        timeout=p.get("timeout", "60s"),
        origin=p.get("origin", ""),
        env=tuple((k, v) for k, v in p.get("env", ())),
        parse=_parse_steps_from_json(p.get("parse", [])),
        path=p.get("path", ""),
    )


def _source_subject(entry: Any) -> str:
    """Stable subject for a source-defined document."""
    if isinstance(entry, TemplateSource):
        return str(entry.template)
    if isinstance(entry, InlineSource):
        return entry.command
    # bare path entry
    return str(entry)


# ===========================================================================
# Public API — decompose and project
# ===========================================================================


def vertex_to_documents(ast: VertexFile) -> list[Document]:
    """Decompose a ``VertexFile`` AST into per-subject declaration documents.

    Emission order (deterministic): the ``_decl.vertex-defined`` singleton,
    then ``_decl.kind-defined`` per loop, ``_decl.observer-defined`` per
    observer, ``_decl.member-defined`` per combine entry, ``_decl.source-defined``
    per source (bare/template entries first, then inline sources per block),
    and ``_decl.lens-defined`` if a lens is declared.

    Each multi-instance document carries an ``order`` field (encounter
    position) and a subject deduplicated per kind (see module docstring:
    "Order is meaning", "Subject uniqueness"). Residence (``store`` locator,
    ``path``) is excluded. Every payload is validated JSON-safe before return.
    """
    docs: list[Document] = []
    order = 0  # global encounter position across all multi-instance documents

    # Per-kind subject deduplication. Allocate against the SET of subjects
    # already issued for this kind (not a per-base counter) so a suffix never
    # lands on a naturally-occurring subject: bases ["base", "base", "base#2"]
    # → ["base", "base#2", "base#3"], all distinct. Identity only — projection
    # reconstructs every value from the payload, never from the subject.
    issued: dict[str, set[str]] = {}

    def _subject(kind: str, base: str) -> str:
        seen = issued.setdefault(kind, set())
        candidate = base
        n = 1
        while candidate in seen:
            n += 1
            candidate = f"{base}#{n}"
        seen.add(candidate)
        return candidate

    def _emit(kind: str, base: str, payload: dict[str, Any]) -> None:
        nonlocal order
        payload["order"] = order
        order += 1
        docs.append(Document(kind=kind, subject=_subject(kind, base), payload=payload))

    # vertex-defined singleton — subject is the vertex name (self); no order.
    docs.append(
        Document(
            kind=DECL_VERTEX_DEFINED,
            subject=ast.name,
            payload={
                "name": ast.name,
                "strict": ast.strict,
                "observer_scoped": ast.observer_scoped,
                "discover": ast.discover,
                "emit": ast.emit,
                "routes": dict(ast.routes) if ast.routes is not None else None,
                "vertices": [str(p) for p in ast.vertices]
                if ast.vertices is not None
                else None,
                "boundary": [_boundary_to_json(b) for b in ast.boundary],
                # sources live in their own documents; this flag preserves the
                # None-vs-empty-tuple distinction of VertexFile.sources.
                "sources_present": ast.sources is not None,
                # authoritative block structure (index + mode); None when there
                # are no sources_blocks. Members are the inline source docs.
                "source_blocks": [
                    {"index": i, "mode": b.mode}
                    for i, b in enumerate(ast.sources_blocks)
                ]
                if ast.sources_blocks is not None
                else None,
            },
        )
    )

    # kind-defined per loop (dict preserves insertion order).
    for kind_name, loop in ast.loops.items():
        _emit(DECL_KIND_DEFINED, kind_name, _loop_def_to_payload(loop))

    # observer-defined per observer.
    for obs in ast.observers or ():
        _emit(DECL_OBSERVER_DEFINED, obs.name, _observer_to_payload(obs))

    # member-defined per combine entry.
    for entry in ast.combine or ():
        _emit(DECL_MEMBER_DEFINED, entry.name, _combine_to_payload(entry))

    # source-defined — bare/template entries from VertexFile.sources ...
    for entry in ast.sources or ():
        if isinstance(entry, TemplateSource):
            payload = _template_source_to_payload(entry)
        else:
            payload = {"form": "path", "path": str(entry)}
        _emit(DECL_SOURCE_DEFINED, _source_subject(entry), payload)

    # ... then inline sources from VertexFile.sources_blocks, tagged with
    # their block index so projection can rebuild block grouping.
    for block_idx, block in enumerate(ast.sources_blocks or ()):
        # ast.py's custom frozen decorator rebuilds classes dynamically, so
        # Pyright can't resolve SourcesBlock.sources' type (infers Never).
        for src in block.sources:  # pyright: ignore[reportGeneralTypeIssues]
            _emit(
                DECL_SOURCE_DEFINED,
                _source_subject(src),
                _inline_source_to_payload(src, block=block_idx, mode=block.mode),
            )

    # lens-defined singleton (whole-vertex fold/stream selection).
    if ast.lens is not None:
        _emit(DECL_LENS_DEFINED, ast.name, _lens_to_payload(ast.lens))

    # Enforce JSON safety (finite floats, str keys, JSON scalars) at the source.
    for d in docs:
        _ensure_json_safe(d.payload, f"{d.kind}:{d.subject}")

    return docs


def genesis_payload(ast: VertexFile) -> dict[str, Any]:
    """The genesis event payload: the whole document set + protocol version.

    ``genesis`` opens a store's lineage by absorbing the initial declaration
    whole (SPEC §9.2). JSON-safe; residence excluded like every document.
    """
    return {
        "protocol": DECLARATION_PROTOCOL_VERSION,
        "documents": [d.as_json() for d in vertex_to_documents(ast)],
    }


def _as_triple(item: Any) -> tuple[str, str, dict[str, Any]]:
    """Normalize a document to (kind, subject, payload).

    Accepts :class:`Document` namedtuples and plain mappings with
    ``kind``/``subject``/``payload`` keys (e.g. from a genesis payload).
    """
    if isinstance(item, Document):
        return item.kind, item.subject, item.payload
    return item["kind"], item["subject"], item.get("payload", {})


def _rebuild_sources_blocks(
    source_blocks_decl: list[dict[str, Any]] | None,
    inline_items: list[tuple[int, int, str, str, InlineSource]],
) -> tuple[SourcesBlock, ...] | None:
    """Reassemble ``sources_blocks`` from the singleton's block structure.

    ``source_blocks_decl`` is the authoritative ``[{"index", "mode"}, ...]``
    recorded on the vertex-defined singleton; ``inline_items`` are the inline
    source docs as ``(order, block_index, mode, subject, InlineSource)``. Each
    inline source drops into its block by index, block members ordered by
    ``(order, subject)`` — subject breaks ties deterministically when duplicate
    ``order`` values appear (possible in edit-era document sets). An empty block
    survives as a member-less entry.

    Falls back to inferring blocks from inline tags (mode carried on each
    inline doc) when the singleton has no ``source_blocks`` — tolerating
    documents from an emitter predating the structural record (forward compat).
    """
    ordered = sorted(inline_items, key=lambda t: (t[0], t[3]))  # (order, subject)
    by_block: dict[int, list[InlineSource]] = {}
    for _order, block_idx, _mode, _subject, src in ordered:
        by_block.setdefault(block_idx, []).append(src)

    if source_blocks_decl is not None:
        return tuple(
            SourcesBlock(
                mode=entry["mode"],
                sources=tuple(by_block.get(entry["index"], ())),
            )
            for entry in source_blocks_decl
        )

    if not inline_items:
        return None

    # Fallback: no structural record — group by block index in first-seen
    # order, taking each block's mode from its first inline source's doc.
    mode_by_block: dict[int, str] = {}
    order_seen: list[int] = []
    for _order, block_idx, mode, _subject, _src in ordered:
        if block_idx not in mode_by_block:
            order_seen.append(block_idx)
            mode_by_block[block_idx] = mode
    return tuple(
        SourcesBlock(mode=mode_by_block[i], sources=tuple(by_block[i]))
        for i in order_seen
    )


def documents_to_vertex(
    documents: Any,
    *,
    path: Path | None = None,
    store: Path | None = None,
) -> VertexFile:
    """Project declaration documents back to a ``VertexFile`` AST.

    ``path`` and ``store`` are residence, supplied by the caller — they are
    not present in the documents. Pure inverse of :func:`vertex_to_documents`
    modulo those two fields.

    Forward-compatible (normative, SPEC §9.2): unknown ``_decl.*`` kinds are
    skipped, and unknown fields inside a known document are ignored, so a
    newer protocol's documents project safely under this reader.
    """
    name: str | None = None
    strict = False
    observer_scoped = False
    discover: str | None = None
    emit: str | None = None
    routes: dict[str, str] | None = None
    vertices: tuple[Path, ...] | None = None
    boundary: tuple[Any, ...] = ()
    sources_present = False
    # authoritative block structure from the vertex-defined singleton.
    source_blocks_decl: list[dict[str, Any]] | None = None

    # Collect multi-instance docs as (order, subject, value) so structure is
    # restored by sorting on (order, subject) — encounter order is meaning.
    kind_items: list[tuple[int, str, LoopDef]] = []
    observer_items: list[tuple[int, str, ObserverDecl]] = []
    member_items: list[tuple[int, str, CombineEntry]] = []
    lens_items: list[tuple[int, str, LensDecl]] = []
    bare_items: list[tuple[int, str, Any]] = []  # path / template entries
    # (order, block_index, mode, subject, InlineSource)
    inline_items: list[tuple[int, int, str, str, InlineSource]] = []

    def _order(p: dict[str, Any]) -> int:
        return p.get("order", 0)

    for item in documents:
        kind, subject, payload = _as_triple(item)

        if kind == DECL_VERTEX_DEFINED:
            name = payload["name"]
            strict = payload.get("strict", False)
            observer_scoped = payload.get("observer_scoped", False)
            discover = payload.get("discover")
            emit = payload.get("emit")
            r = payload.get("routes")
            routes = dict(r) if r is not None else None
            v = payload.get("vertices")
            vertices = tuple(Path(p) for p in v) if v is not None else None
            boundary = tuple(_boundary_from_json(b) for b in payload.get("boundary", ()))
            sources_present = payload.get("sources_present", False)
            source_blocks_decl = payload.get("source_blocks")

        elif kind == DECL_KIND_DEFINED:
            kind_items.append((_order(payload), subject, _loop_def_from_payload(payload)))

        elif kind == DECL_OBSERVER_DEFINED:
            observer_items.append((_order(payload), subject, _observer_from_payload(payload)))

        elif kind == DECL_MEMBER_DEFINED:
            member_items.append((_order(payload), subject, _combine_from_payload(payload)))

        elif kind == DECL_LENS_DEFINED:
            lens_items.append((_order(payload), subject, _lens_from_payload(payload)))

        elif kind == DECL_SOURCE_DEFINED:
            form = payload.get("form")
            if form == "path":
                bare_items.append((_order(payload), subject, Path(payload["path"])))
            elif form == "template":
                bare_items.append(
                    (_order(payload), subject, _template_source_from_payload(payload))
                )
            elif form == "inline":
                inline_items.append(
                    (
                        _order(payload),
                        payload["block"],
                        payload.get("mode", "sequential"),
                        subject,
                        _inline_source_from_payload(payload),
                    )
                )
            # unknown form → skip (forward compat)

        # unknown _decl.* kind → skip (forward compat)

    if name is None:
        raise ValueError("documents missing a _decl.vertex-defined singleton")

    # kind-defined: dict rebuilt in (order, subject) order.
    loops: dict[str, LoopDef] = {}
    for _o, subject, loop in sorted(kind_items, key=lambda t: (t[0], t[1])):
        loops[subject] = loop

    observers = [o for _o, _s, o in sorted(observer_items, key=lambda t: (t[0], t[1]))]
    combine = [c for _o, _s, c in sorted(member_items, key=lambda t: (t[0], t[1]))]
    lens = (
        sorted(lens_items, key=lambda t: (t[0], t[1]))[0][2] if lens_items else None
    )

    # Reassemble VertexFile.sources (bare/template entries) in (order, subject).
    bare_sorted = [e for _o, _s, e in sorted(bare_items, key=lambda t: (t[0], t[1]))]
    sources: tuple[Any, ...] | None
    if bare_sorted:
        sources = tuple(bare_sorted)
    elif sources_present:
        sources = ()  # empty `sources {}` block — the one reachable empty tuple
    else:
        sources = None

    sources_blocks = _rebuild_sources_blocks(source_blocks_decl, inline_items)

    return VertexFile(
        name=name,
        loops=loops,
        store=store,
        discover=discover,
        sources=sources,
        vertices=vertices,
        routes=routes,
        emit=emit,
        combine=tuple(combine) if combine else None,
        sources_blocks=sources_blocks,
        observers=tuple(observers) if observers else None,
        lens=lens,
        boundary=boundary,
        observer_scoped=observer_scoped,
        strict=strict,
        path=path,
    )


# ===========================================================================
# Subject-granular diff — the edit ceremony's grammar half (SPEC §9.2, S4)
# ===========================================================================
#
# Re-absorbing an edited ``.vertex`` diffs its freshly-parsed document set
# against the store's fold head (Latest per (kind, subject), self-lineage) and
# re-emits ONLY the changed subjects as whole documents. This module supplies
# the pure-grammar half: comparing two document sets. The store half (stamping
# lineage, signing, appending atomically) lives in ``engine.sqlite_store``.
#
# Whole-document only (SPEC §9.2): a subject is "changed" iff its complete
# payload — INCLUDING the ``order`` field — differs by value. There are no
# facet deltas. This makes the round-trip exact (the resolver's overlay fold,
# applied over the head, reproduces the edited file's document set) and
# idempotence exact (an unchanged file re-parses to identical payloads, so the
# diff is empty). ``order`` is a dense global counter, so a structural insert
# shifts downstream subjects' ``order`` and honestly re-emits them — "order is
# meaning" (see module docstring).


#: Inverse of :data:`DEFINED_TO_TOMBSTONE`: which ``*-defined`` subject a
#: tombstone kind removes. Used by :func:`apply_changes` to fold a removal.
_TOMBSTONE_TO_DEFINED: dict[str, str] = {v: k for k, v in DEFINED_TO_TOMBSTONE.items()}


class EditRefused(ValueError):
    """A re-absorb edit is inexpressible in the frozen declaration vocabulary.

    Two cases, both structural refusals rather than silent lies:

    - **Singleton removal.** Dropping a ``_decl.lens-defined`` has no tombstone
      in the code-frozen vocabulary (SPEC §9.2 — a lens is "replaced by
      re-definition"), so removal cannot be recorded. Rather than mint a new
      kind unilaterally (thread:decl-lens-tombstone-vocab-gap, a later
      coordinated change with the loops-go oracle), the ceremony refuses.

    - **Identity change.** The ``_decl.vertex-defined`` singleton's subject is
      the vertex name; a rename would surface as remove-old + add-new. The name
      is meaning-critical self-description, so a post-genesis rename is a
      deliberate identity ceremony, never a routine edit — refused.
    """


class Change(NamedTuple):
    """One subject-granular declaration change (SPEC §9.2, S4).

    ``kind`` is the FINAL event kind: a ``_decl.*-defined`` kind for an
    add/modify, or the paired ``_decl.*-retired``/``-removed`` tombstone for a
    removal. ``payload`` is the whole document payload for a definition, or
    ``None`` for a removal. ``annotation`` is the ``change=`` legibility label —
    ``"added"``, ``"modified"``, or ``"removed"`` (SPEC §9.2: "MAY carry a
    ``change`` annotation"). Emitters ride ``annotation`` on the row as
    ``change=``; the resolver ignores it.
    """

    kind: str
    subject: str
    payload: dict[str, Any] | None
    annotation: str


def diff_documents(head: Any, new: Any) -> list[Change]:
    """Diff a fold head against a freshly-parsed document set → changes.

    ``head`` and ``new`` are each an iterable of documents — :class:`Document`
    namedtuples or plain ``{"kind", "subject", "payload"}`` mappings (the
    resolver returns the latter). Both are keyed by ``(kind, subject)``.

    Yields (in a deterministic order — additions/modifications in ``new``'s
    iteration order, then removals in ``head``'s iteration order):

    - ``"added"`` — a ``(kind, subject)`` in ``new`` but not ``head``.
    - ``"modified"`` — present in both, payloads differ by value.
    - ``"removed"`` — in ``head`` but not ``new``; emitted as the paired
      tombstone kind.

    Raises :class:`EditRefused` if a removal targets a singleton with no
    tombstone (``_decl.lens-defined`` → vocabulary gap; ``_decl.vertex-defined``
    → identity/rename). Unchanged subjects yield nothing.
    """
    head_map: dict[tuple[str, str], dict[str, Any]] = {}
    for item in head:
        k, s, p = _as_triple(item)
        head_map[(k, s)] = p

    new_map: dict[tuple[str, str], dict[str, Any]] = {}
    changes: list[Change] = []
    for item in new:
        k, s, p = _as_triple(item)
        new_map[(k, s)] = p
        prev = head_map.get((k, s))
        if prev is None:
            changes.append(Change(kind=k, subject=s, payload=p, annotation="added"))
        elif prev != p:
            changes.append(Change(kind=k, subject=s, payload=p, annotation="modified"))
        # else unchanged → nothing

    for (k, s), _p in head_map.items():
        if (k, s) in new_map:
            continue
        tombstone = DEFINED_TO_TOMBSTONE.get(k)
        if tombstone is None:
            if k == DECL_VERTEX_DEFINED:
                raise EditRefused(
                    f"vertex identity change: the vertex-defined subject "
                    f"{s!r} was removed (a rename). The vertex name is "
                    "meaning-critical identity — a post-genesis rename is a "
                    "deliberate ceremony, not an edit; not supported by "
                    "re-absorb."
                )
            raise EditRefused(
                f"cannot remove singleton {k!r} (subject {s!r}): the frozen "
                "declaration vocabulary has no tombstone for it "
                "(SPEC §9.2 — a lens is replaced by re-definition, never "
                "removed). Re-add the lens, or edit it in place; removal is a "
                "pending coordinated vocabulary change "
                "(thread:decl-lens-tombstone-vocab-gap)."
            )
        changes.append(Change(kind=tombstone, subject=s, payload=None, annotation="removed"))

    return changes


def apply_changes(head: Any, changes: Any) -> list[dict[str, Any]]:
    """Fold ``changes`` over ``head`` → the resulting document set (pure).

    Mirrors the store resolver's overlay/tombstone fold
    (``engine.declaration.resolve_declaration_documents``) at the grammar tier,
    with NO store: a ``*-defined`` change replaces its ``(kind, subject)``
    document; a tombstone removes the paired ``*-defined`` subject. Returned
    documents are ``{"kind", "subject", "payload"}`` dicts in insertion order
    (definitions keep position across replacement).

    This is the reconstruction oracle for the diff property test:
    ``apply_changes(head, diff_documents(head, new))`` equals ``new`` as a
    document set. It intentionally re-implements the fold independently of the
    engine resolver so the two agree by construction, not by shared code.
    """
    docs: dict[tuple[str, str], dict[str, Any]] = {}
    for item in head:
        k, s, p = _as_triple(item)
        docs[(k, s)] = {"kind": k, "subject": s, "payload": p}

    for ch in changes:
        kind, subject, payload, _annotation = (
            (ch.kind, ch.subject, ch.payload, ch.annotation)
            if isinstance(ch, Change)
            else (ch["kind"], ch["subject"], ch.get("payload"), ch.get("change"))
        )
        defined = _TOMBSTONE_TO_DEFINED.get(kind)
        if defined is not None:
            docs.pop((defined, subject), None)
        else:
            docs[(kind, subject)] = {
                "kind": kind,
                "subject": subject,
                "payload": payload if payload is not None else {},
            }

    return list(docs.values())

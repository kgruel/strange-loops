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
"""

from __future__ import annotations

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

    Residence (``store`` locator, ``path``) is excluded — supplied at
    projection time, not carried in documents.
    """
    docs: list[Document] = []

    # vertex-defined singleton — subject is the vertex name (self).
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
            },
        )
    )

    # kind-defined per loop (dict preserves insertion order).
    for kind_name, loop in ast.loops.items():
        docs.append(
            Document(
                kind=DECL_KIND_DEFINED,
                subject=kind_name,
                payload=_loop_def_to_payload(loop),
            )
        )

    # observer-defined per observer.
    for obs in ast.observers or ():
        docs.append(
            Document(
                kind=DECL_OBSERVER_DEFINED,
                subject=obs.name,
                payload=_observer_to_payload(obs),
            )
        )

    # member-defined per combine entry.
    for entry in ast.combine or ():
        docs.append(
            Document(
                kind=DECL_MEMBER_DEFINED,
                subject=entry.name,
                payload=_combine_to_payload(entry),
            )
        )

    # source-defined — bare/template entries from VertexFile.sources ...
    for entry in ast.sources or ():
        if isinstance(entry, TemplateSource):
            payload = _template_source_to_payload(entry)
        else:
            payload = {"form": "path", "path": str(entry)}
        docs.append(
            Document(
                kind=DECL_SOURCE_DEFINED,
                subject=_source_subject(entry),
                payload=payload,
            )
        )

    # ... then inline sources from VertexFile.sources_blocks, tagged with
    # their block index + mode so grouping reconstructs exactly.
    for block_idx, block in enumerate(ast.sources_blocks or ()):
        for src in block.sources:
            docs.append(
                Document(
                    kind=DECL_SOURCE_DEFINED,
                    subject=_source_subject(src),
                    payload=_inline_source_to_payload(
                        src, block=block_idx, mode=block.mode
                    ),
                )
            )

    # lens-defined singleton (whole-vertex fold/stream selection).
    if ast.lens is not None:
        docs.append(
            Document(
                kind=DECL_LENS_DEFINED,
                subject=ast.name,
                payload=_lens_to_payload(ast.lens),
            )
        )

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

    loops: dict[str, LoopDef] = {}
    observers: list[ObserverDecl] = []
    combine: list[CombineEntry] = []
    lens: LensDecl | None = None

    # Source reassembly: bare/template entries in encountered order; inline
    # sources grouped by block index (first-seen order) with per-block mode.
    source_entries: list[Any] = []
    blocks: dict[int, dict[str, Any]] = {}
    block_order: list[int] = []

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

        elif kind == DECL_KIND_DEFINED:
            loops[subject] = _loop_def_from_payload(payload)

        elif kind == DECL_OBSERVER_DEFINED:
            observers.append(_observer_from_payload(payload))

        elif kind == DECL_MEMBER_DEFINED:
            combine.append(_combine_from_payload(payload))

        elif kind == DECL_LENS_DEFINED:
            lens = _lens_from_payload(payload)

        elif kind == DECL_SOURCE_DEFINED:
            form = payload.get("form")
            if form == "path":
                source_entries.append(Path(payload["path"]))
            elif form == "template":
                source_entries.append(_template_source_from_payload(payload))
            elif form == "inline":
                block_idx = payload["block"]
                if block_idx not in blocks:
                    blocks[block_idx] = {"mode": payload["mode"], "sources": []}
                    block_order.append(block_idx)
                blocks[block_idx]["sources"].append(
                    _inline_source_from_payload(payload)
                )
            # unknown form → skip (forward compat)

        # unknown _decl.* kind → skip (forward compat)

    if name is None:
        raise ValueError("documents missing a _decl.vertex-defined singleton")

    # Reassemble VertexFile.sources: None unless entries present or the
    # singleton recorded an (empty) sources block.
    sources: tuple[Any, ...] | None
    if source_entries:
        sources = tuple(source_entries)
    elif sources_present:
        sources = ()
    else:
        sources = None

    sources_blocks: tuple[SourcesBlock, ...] | None = (
        tuple(
            SourcesBlock(
                mode=blocks[i]["mode"], sources=tuple(blocks[i]["sources"])
            )
            for i in block_order
        )
        if block_order
        else None
    )

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

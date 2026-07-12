"""Round-trip and forward-compat tests for the declaration document form.

The AST classes are frozen dataclasses with a generated structural ``__eq__``
(see ``ast.py`` ``_frozen``), so ``==`` compares field tuples recursively —
we can assert projected-AST equality directly. Residence (``path``, ``store``)
is stripped from documents, so round-trip tests supply the *original*
residence back at projection time; the projected AST then equals the original
exactly.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from lang import parse_vertex
from lang.ast import (
    BoundaryCondition,
    BoundaryWhen,
    CombineEntry,
    FoldCount,
    FoldDecl,
    InlineSource,
    LoopDef,
    SourcesBlock,
    VertexFile,
)
from lang.document import (
    DECL_KIND_DEFINED,
    DECL_LENS_DEFINED,
    DECL_MEMBER_DEFINED,
    DECL_OBSERVER_DEFINED,
    DECL_PREFIX,
    DECL_SOURCE_DEFINED,
    DECL_VERTEX_DEFINED,
    DECLARATION_PROTOCOL_VERSION,
    Document,
    documents_to_vertex,
    genesis_payload,
    is_internal_kind,
    vertex_to_documents,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Synthesized KDL exercising every union member + declaration surface
# ---------------------------------------------------------------------------

# Every fold op, every parse step, every transform op, a full boundary with
# match + conditions + run, edges, search, preview.
KITCHEN_SINK = """
name "kitchen"
store "./data/kitchen.db"
strict true
scope "observer"
emit "kitchen.default"
discover "./children/**/*.vertex"
vertices "./a/a.vertex" "./b/b.vertex"

loops {
  boundary when="session" status="closed" {
    condition "high" ">=" 80
    run "scripts/seal.sh"
  }
  boundary after=100 {
    run "scripts/checkpoint.sh"
  }
  boundary every=10

  metric {
    fold {
      byfield "by" "topic"
      counter "count"
      total "sum" "amount"
      recent "latest"
      history "collect" 50
      peak "max" "value"
      trough "min" "value"
      mean "avg" "value"
      slide "window" 5 "value"
    }
    boundary when="metric.done"
    search "topic" "amount"
    preview "topic" "amount"
    edge "stakeholder" targets="person"
    edge "owner" targets="team"
    parse {
      skip "^#"
      split ","
      pick 0 2 {
        names "topic" "amount"
      }
      select "topic" "amount"
      transform "amount" {
        strip "$"
        lstrip " "
        rstrip " "
        replace "," ""
        coerce "float"
      }
      explode path="items" carry="topic:group,amount:amt"
      project {
        label path="a.b.c"
      }
      where path="type" "in" "user" "assistant"
      flatten "events" into="text" {
        extract "name" "value"
      }
    }
  }

  simple {
    fold {
      n "inc"
    }
  }
}

routes {
  "metric.*" "metric"
  simple "simple"
}

observers {
  alice {
    key "AAAAC3NzaC1lZDI1NTE5AAAAIexamplekeymaterialbase64=="
    identity "identity/alice"
    grant {
      potential "metric" "simple"
    }
  }
  bob {
    key "BBBBC3NzaC1lZDI1NTE5AAAAIexamplekeymaterialbase64=="
  }
}

lens {
  fold "reconcile"
  stream "timeline"
}
"""

# where op variants not covered above (equals / not_equals / exists / not_in),
# split with default (whitespace) delimiter, pick without names.
WHERE_VARIANTS = """
name "wherevar"
store "./w.db"
loops {
  rows {
    fold { n "inc" }
    parse {
      split
      pick 0 1
      where path="a" equals="x"
      where path="b" not_equals="y"
      where path="c" exists=true
      where path="d" "not_in" "p" "q"
    }
  }
}
"""

# Template sources: one with inline `with` rows + a loop spec, one with a
# `from file` external param source.
TEMPLATE_SOURCES = """
name "templated"
store "./t.db"
sources {
  path "./monitor.loop"
  template "./feed.loop" {
    with url="https://a.example" tag="a"
    with url="https://b.example" tag="b"
    loop {
      fold { items "collect" 20 }
      boundary when="feed.done"
    }
  }
  template "./ext.loop" {
    from file "./params.list"
  }
}
loops {
  local {
    fold { n "inc" }
  }
}
"""

# sources blocks (sequential execution mode) with full inline-source vocab,
# including a trigger, env, parse, origin, timeout.
SOURCES_BLOCKS = """
name "seqsources"
store "./s.db"
sources sequential {
  source "curl -s https://a.example" {
    kind "alpha"
    observer "fetcher"
    every "30s"
    format "json"
    timeout "45s"
    origin "remote-a"
    env KEY="v1" TOKEN="v2"
    parse {
      split "|"
    }
  }
  source "curl -s https://b.example" {
    kind "beta"
    on "alpha.done" "gamma.done"
    path "beta/path"
  }
}
loops {
  alpha { fold { n "inc" } }
  beta { fold { n "inc" } }
}
"""

# combine (aggregation) vertex — mutually exclusive with store/sources.
COMBINE = """
name "aggregate"
combine {
  vertex "project" as="proj"
  vertex "/abs/path/meta.vertex"
}
"""

# Two inline sources sharing a command → same subject base → collision suffix.
COLLISION_SOURCES = """
name "coll"
store "./c.db"
sources sequential {
  source "echo x" {
    kind "a"
  }
  source "echo x" {
    kind "b"
  }
}
loops {
  a { fold { n "inc" } }
  b { fold { n "inc" } }
}
"""

SYNTH_CASES = {
    "kitchen_sink": KITCHEN_SINK,
    "where_variants": WHERE_VARIANTS,
    "template_sources": TEMPLATE_SOURCES,
    "sources_blocks": SOURCES_BLOCKS,
    "combine": COMBINE,
    "collision_sources": COLLISION_SOURCES,
}


def _fixture_vertex_texts() -> dict[str, str]:
    return {p.name: p.read_text() for p in FIXTURES.glob("*.vertex")}


ALL_CASES = {
    **SYNTH_CASES,
    **{f"fixture:{n}": t for n, t in _fixture_vertex_texts().items()},
}


# ---------------------------------------------------------------------------
# Round-trip: parse → documents → project → equal AST (modulo residence)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(ALL_CASES))
def test_roundtrip_via_documents(name: str) -> None:
    text = ALL_CASES[name]
    ast = parse_vertex(text)
    docs = vertex_to_documents(ast)
    # Supply the original residence back at projection time.
    projected = documents_to_vertex(docs, path=ast.path, store=ast.store)
    assert projected == ast


@pytest.mark.parametrize("name", sorted(ALL_CASES))
def test_roundtrip_via_genesis(name: str) -> None:
    text = ALL_CASES[name]
    ast = parse_vertex(text)
    payload = genesis_payload(ast)
    assert payload["protocol"] == DECLARATION_PROTOCOL_VERSION
    projected = documents_to_vertex(
        payload["documents"], path=ast.path, store=ast.store
    )
    assert projected == ast


@pytest.mark.parametrize("name", sorted(ALL_CASES))
def test_roundtrip_is_idempotent(name: str) -> None:
    """documents(project(documents(ast))) is byte-identical to documents(ast)."""
    ast = parse_vertex(ALL_CASES[name])
    docs1 = vertex_to_documents(ast)
    ast2 = documents_to_vertex(docs1, path=ast.path, store=ast.store)
    docs2 = vertex_to_documents(ast2)
    assert [d.as_json() for d in docs1] == [d.as_json() for d in docs2]


# ---------------------------------------------------------------------------
# JSON safety — payloads are strictly JSON types (no tuples/sets/NaN)
# ---------------------------------------------------------------------------

def _assert_json_pure(obj: object, where: str) -> None:
    if isinstance(obj, bool) or obj is None or isinstance(obj, (str, int)):
        return
    if isinstance(obj, float):
        assert obj == obj and obj not in (float("inf"), float("-inf")), (
            f"non-finite float at {where}"
        )
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert isinstance(k, str), f"non-str dict key at {where}: {k!r}"
            _assert_json_pure(v, f"{where}.{k}")
        return
    if isinstance(obj, list):
        for i, v in enumerate(obj):
            _assert_json_pure(v, f"{where}[{i}]")
        return
    raise AssertionError(f"non-JSON type {type(obj).__name__} at {where}")


@pytest.mark.parametrize("name", sorted(ALL_CASES))
def test_payloads_are_json_safe(name: str) -> None:
    ast = parse_vertex(ALL_CASES[name])
    for doc in vertex_to_documents(ast):
        assert isinstance(doc.kind, str) and is_internal_kind(doc.kind)
        assert isinstance(doc.subject, str)
        _assert_json_pure(doc.payload, f"{doc.kind}:{doc.subject}")
        # json.dumps must succeed with no tolerance for NaN/Infinity.
        json.dumps(doc.payload, allow_nan=False)
    # Whole genesis payload dumps too.
    json.dumps(genesis_payload(ast), allow_nan=False)


# ---------------------------------------------------------------------------
# Structural expectations on the emitted document set
# ---------------------------------------------------------------------------


def test_exactly_one_vertex_defined_singleton() -> None:
    ast = parse_vertex(KITCHEN_SINK)
    docs = vertex_to_documents(ast)
    vdefs = [d for d in docs if d.kind == DECL_VERTEX_DEFINED]
    assert len(vdefs) == 1
    assert vdefs[0].subject == "kitchen"


def test_kind_defined_subjects_match_loops() -> None:
    ast = parse_vertex(KITCHEN_SINK)
    docs = vertex_to_documents(ast)
    subjects = [d.subject for d in docs if d.kind == DECL_KIND_DEFINED]
    assert subjects == list(ast.loops.keys())


def test_observer_public_key_enters_document() -> None:
    ast = parse_vertex(KITCHEN_SINK)
    docs = vertex_to_documents(ast)
    alice = next(
        d for d in docs if d.kind == DECL_OBSERVER_DEFINED and d.subject == "alice"
    )
    assert alice.payload["key"].startswith("AAAA")
    assert alice.payload["grant"]["potential"] == ["metric", "simple"]


def test_store_and_path_never_enter_documents() -> None:
    ast = parse_vertex(KITCHEN_SINK)
    # Parsed from text: path is None but store is set. Give it a path too so
    # we prove neither leaks.
    ast = VertexFile(**{**_vertex_kwargs(ast), "path": Path("/somewhere/x.vertex")})
    blob = json.dumps(genesis_payload(ast))
    assert "kitchen.db" not in blob  # the store locator
    assert "/somewhere/x.vertex" not in blob  # the residence path


def test_source_defined_for_each_source() -> None:
    ast = parse_vertex(TEMPLATE_SOURCES)
    docs = vertex_to_documents(ast)
    srcs = [d for d in docs if d.kind == DECL_SOURCE_DEFINED]
    # one path + two templates
    assert len(srcs) == 3
    forms = sorted(d.payload["form"] for d in srcs)
    assert forms == ["path", "template", "template"]


def test_inline_sources_carry_block_and_mode() -> None:
    ast = parse_vertex(SOURCES_BLOCKS)
    docs = vertex_to_documents(ast)
    inline = [d for d in docs if d.payload.get("form") == "inline"]
    assert len(inline) == 2
    assert all(d.payload["mode"] == "sequential" for d in inline)
    assert all(d.payload["block"] == 0 for d in inline)


def test_lens_defined_singleton_present() -> None:
    ast = parse_vertex(KITCHEN_SINK)
    docs = vertex_to_documents(ast)
    lenses = [d for d in docs if d.kind == DECL_LENS_DEFINED]
    assert len(lenses) == 1
    assert lenses[0].payload["fold"] == "reconcile"
    assert lenses[0].payload["stream"] == "timeline"
    assert isinstance(lenses[0].payload["order"], int)


def test_combine_becomes_member_defined() -> None:
    ast = parse_vertex(COMBINE)
    docs = vertex_to_documents(ast)
    members = [d for d in docs if d.kind == DECL_MEMBER_DEFINED]
    assert [d.subject for d in members] == ["project", "/abs/path/meta.vertex"]
    assert members[0].payload["name"] == "project"
    assert members[0].payload["alias"] == "proj"


# ---------------------------------------------------------------------------
# None-vs-empty residence-independent distinctions
# ---------------------------------------------------------------------------


def test_empty_sources_block_roundtrips_as_empty_tuple() -> None:
    ast = parse_vertex('name "x"\nstore "./x.db"\nsources {\n}\nloops { c { fold { n "inc" } } }')
    assert ast.sources == ()
    projected = documents_to_vertex(
        vertex_to_documents(ast), path=ast.path, store=ast.store
    )
    assert projected.sources == ()
    assert projected == ast


def test_absent_sources_roundtrips_as_none() -> None:
    ast = parse_vertex(KITCHEN_SINK)  # no `sources` node → None
    assert ast.sources is None
    projected = documents_to_vertex(
        vertex_to_documents(ast), path=ast.path, store=ast.store
    )
    assert projected.sources is None


# ---------------------------------------------------------------------------
# Forward compatibility (normative, SPEC §9.2)
# ---------------------------------------------------------------------------


def test_unknown_decl_kind_is_skipped() -> None:
    ast = parse_vertex(KITCHEN_SINK)
    docs = vertex_to_documents(ast)
    docs.append(Document(kind="_decl.future-thing", subject="whatever", payload={"x": 1}))
    projected = documents_to_vertex(docs, path=ast.path, store=ast.store)
    assert projected == ast


def test_unknown_field_in_document_is_ignored() -> None:
    ast = parse_vertex(KITCHEN_SINK)
    docs = vertex_to_documents(ast)
    # Inject an unknown field into the vertex-defined payload.
    patched = []
    for d in docs:
        if d.kind == DECL_VERTEX_DEFINED:
            patched.append(Document(d.kind, d.subject, {**d.payload, "future_flag": 42}))
        else:
            patched.append(d)
    projected = documents_to_vertex(patched, path=ast.path, store=ast.store)
    assert projected == ast


def test_documents_to_vertex_accepts_mapping_form() -> None:
    ast = parse_vertex(KITCHEN_SINK)
    as_dicts = [d.as_json() for d in vertex_to_documents(ast)]
    projected = documents_to_vertex(as_dicts, path=ast.path, store=ast.store)
    assert projected == ast


def test_missing_vertex_defined_raises() -> None:
    with pytest.raises(ValueError, match="vertex-defined"):
        documents_to_vertex([Document(DECL_KIND_DEFINED, "c", {"folds": []})])


def test_nested_unknown_field_ignored() -> None:
    """Unknown fields inside nested union dicts (fold op, boundary, parse step,
    source payload) are ignored, not fatal."""
    ast = parse_vertex(KITCHEN_SINK)
    docs = vertex_to_documents(ast)
    patched: list[Document] = []
    for d in docs:
        p = json.loads(json.dumps(d.payload))  # deep copy
        if d.kind == DECL_KIND_DEFINED and p.get("folds"):
            p["folds"][0]["op"]["future_op_field"] = "x"  # inside a fold op
            if p.get("boundary") is not None:
                p["boundary"]["future_boundary_field"] = "y"  # inside a boundary
            if p.get("parse"):
                p["parse"][0]["future_step_field"] = "z"  # inside a parse step
        if d.kind == DECL_SOURCE_DEFINED:
            p["future_source_field"] = "s"
        patched.append(Document(d.kind, d.subject, p))
    projected = documents_to_vertex(patched, path=ast.path, store=ast.store)
    assert projected == ast


# ---------------------------------------------------------------------------
# Subject collision suffixing (protocol: (kind, subject) must be unique)
# ---------------------------------------------------------------------------


def test_source_subject_collision_suffix() -> None:
    ast = parse_vertex(COLLISION_SOURCES)
    docs = vertex_to_documents(ast)
    subjects = [d.subject for d in docs if d.kind == DECL_SOURCE_DEFINED]
    assert subjects == ["echo x", "echo x#2"]  # deterministic, encounter order
    # (kind, subject) pairs are globally unique across the document set.
    pairs = [(d.kind, d.subject) for d in docs]
    assert len(pairs) == len(set(pairs))
    # And both colliding sources survive the round-trip.
    projected = documents_to_vertex(docs, path=ast.path, store=ast.store)
    assert projected == ast


def test_suffix_allocation_avoids_natural_subject() -> None:
    """Bases ["base", "base", "base#2"] must not re-collide — the allocator
    bumps past a naturally-occurring 'base#2' rather than re-issuing it."""
    ast = VertexFile(
        name="x",
        loops={},
        sources_blocks=(
            SourcesBlock(
                mode="sequential",
                sources=(
                    InlineSource(command="base", kind="a"),
                    InlineSource(command="base", kind="b"),
                    InlineSource(command="base#2", kind="c"),
                ),
            ),
        ),
    )
    docs = vertex_to_documents(ast)
    subjects = [d.subject for d in docs if d.kind == DECL_SOURCE_DEFINED]
    # The literal 'base#2' third source can't reuse the issued 'base#2'; the
    # allocator bumps it to a distinct, deterministic subject.
    assert subjects == ["base", "base#2", "base#2#2"]
    assert len(subjects) == len(set(subjects))  # all distinct — nothing dropped
    projected = documents_to_vertex(docs, path=ast.path, store=ast.store)
    assert projected == ast  # all three sources survive


def test_inline_projection_tie_break_is_stable() -> None:
    """Two inline docs with equal `order` project in a stable order (by
    subject), independent of input list order."""
    ast = VertexFile(
        name="x",
        loops={},
        sources_blocks=(
            SourcesBlock(
                mode="sequential",
                sources=(
                    InlineSource(command="aaa", kind="k"),
                    InlineSource(command="bbb", kind="k"),
                ),
            ),
        ),
    )
    docs = vertex_to_documents(ast)
    # Force the two inline docs to collide on `order` (edit-era scenario).
    for d in docs:
        if d.payload.get("form") == "inline":
            d.payload["order"] = 5
    proj_forward = documents_to_vertex(docs, path=ast.path, store=ast.store)
    proj_reversed = documents_to_vertex(
        list(reversed(docs)), path=ast.path, store=ast.store
    )
    assert proj_forward == proj_reversed
    commands = [s.command for s in proj_forward.sources_blocks[0].sources]
    assert commands == ["aaa", "bbb"]  # subject tie-break, deterministic


def test_combine_subject_collision_suffix() -> None:
    # Duplicate member names — construct directly (loader would also allow it).
    ast = VertexFile(
        name="dup",
        loops={},
        combine=(
            CombineEntry(name="shared", alias="first"),
            CombineEntry(name="shared", alias="second"),
        ),
    )
    docs = vertex_to_documents(ast)
    members = [d for d in docs if d.kind == DECL_MEMBER_DEFINED]
    assert [d.subject for d in members] == ["shared", "shared#2"]
    projected = documents_to_vertex(docs, path=ast.path, store=ast.store)
    assert projected == ast  # both entries, in order


# ---------------------------------------------------------------------------
# Order preservation (order survives shuffling the document set)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(ALL_CASES))
def test_order_preserved_after_shuffle(name: str) -> None:
    ast = parse_vertex(ALL_CASES[name])
    docs = vertex_to_documents(ast)
    shuffled = list(docs)
    random.Random(1234).shuffle(shuffled)
    projected = documents_to_vertex(shuffled, path=ast.path, store=ast.store)
    assert projected == ast


def test_kind_order_survives_shuffle_specifically() -> None:
    """A multi-loop vertex keeps loop declaration order after a shuffle."""
    ast = parse_vertex(SOURCES_BLOCKS)  # loops: alpha then beta
    assert list(ast.loops) == ["alpha", "beta"]
    docs = vertex_to_documents(ast)
    shuffled = list(docs)
    random.Random(99).shuffle(shuffled)
    projected = documents_to_vertex(shuffled, path=ast.path, store=ast.store)
    assert list(projected.loops) == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# Empty SourcesBlock (structural record on the singleton; parser-unreachable
# but preserved when supplied directly, e.g. via edit or a future emitter)
# ---------------------------------------------------------------------------


def test_empty_source_block_survives_projection() -> None:
    docs = [
        Document(
            DECL_VERTEX_DEFINED,
            "e",
            {
                "name": "e",
                "strict": False,
                "observer_scoped": False,
                "discover": None,
                "emit": None,
                "routes": None,
                "vertices": None,
                "boundary": [],
                "sources_present": False,
                "source_blocks": [{"index": 0, "mode": "sequential"}],
            },
        ),
        Document(DECL_KIND_DEFINED, "c", {"folds": [], "order": 0}),
    ]
    projected = documents_to_vertex(docs)
    assert projected.sources_blocks is not None
    assert len(projected.sources_blocks) == 1
    assert projected.sources_blocks[0].mode == "sequential"
    assert projected.sources_blocks[0].sources == ()  # member-less block


# ---------------------------------------------------------------------------
# JSON-safety enforcement at serialization (NaN/Infinity, non-str keys)
# ---------------------------------------------------------------------------


def _one_loop() -> dict:
    return {"c": LoopDef(folds=(FoldDecl(target="n", op=FoldCount()),))}


def test_nan_boundary_condition_rejected() -> None:
    ast = VertexFile(
        name="x",
        loops={
            "c": LoopDef(
                folds=(FoldDecl(target="n", op=FoldCount()),),
                boundary=BoundaryWhen(
                    kind="s",
                    conditions=(
                        BoundaryCondition(target="h", op=">=", value=float("nan")),
                    ),
                ),
            )
        },
    )
    with pytest.raises(ValueError, match="non-finite float"):
        vertex_to_documents(ast)


def test_infinity_boundary_condition_rejected() -> None:
    ast = VertexFile(
        name="x",
        loops={
            "c": LoopDef(
                folds=(FoldDecl(target="n", op=FoldCount()),),
                boundary=BoundaryWhen(
                    kind="s",
                    conditions=(
                        BoundaryCondition(target="h", op=">=", value=float("inf")),
                    ),
                ),
            )
        },
    )
    with pytest.raises(ValueError, match="non-finite float"):
        vertex_to_documents(ast)


def test_non_str_dict_key_rejected() -> None:
    # routes is dict[str, str] by contract; a non-str key must be caught here.
    ast = VertexFile(name="x", loops=_one_loop(), routes={123: "c"})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="non-str dict key"):
        vertex_to_documents(ast)


# ---------------------------------------------------------------------------
# is_internal_kind truth table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("_decl.genesis", True),
        ("_decl.kind-defined", True),
        ("_decl.anything-future", True),
        ("_decl.", True),
        (DECL_PREFIX, True),
        ("decision", False),
        ("_topology", False),
        ("_decl", False),  # no trailing dot — not in namespace
        ("thing._decl.x", False),
        ("", False),
    ],
)
def test_is_internal_kind_truth_table(kind: str, expected: bool) -> None:
    assert is_internal_kind(kind) is expected


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _vertex_kwargs(ast: VertexFile) -> dict:
    """Extract the constructor kwargs of a VertexFile (for rebuilding copies)."""
    return {
        "name": ast.name,
        "loops": ast.loops,
        "store": ast.store,
        "discover": ast.discover,
        "sources": ast.sources,
        "vertices": ast.vertices,
        "routes": ast.routes,
        "emit": ast.emit,
        "combine": ast.combine,
        "sources_blocks": ast.sources_blocks,
        "observers": ast.observers,
        "lens": ast.lens,
        "boundary": ast.boundary,
        "observer_scoped": ast.observer_scoped,
        "strict": ast.strict,
        "path": ast.path,
    }

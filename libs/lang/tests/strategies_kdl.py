"""Hypothesis strategies for KDL AST generation and roundtrip property tests.

Generators build KDL documents compositionally from ckdl's AST node constructors:
- Nodes, nested children, arguments, and properties.
- Value types: strings (unicode, ASCII), integers, floats (exact decimal representations),
  booleans, and nulls.
- Unicode and bare identifiers.
- Empty documents and documents with varying nesting depths.
- Declarative LoopDef and .vertex document structures for mutation testing.
"""

from __future__ import annotations

from typing import Any

import ckdl
from hypothesis import strategies as st

from lang.ast import (
    BoundaryAfter,
    BoundaryCondition,
    BoundaryEvery,
    BoundaryWhen,
    EdgeDecl,
    FoldAvg,
    FoldBy,
    FoldCollect,
    FoldCount,
    FoldDecl,
    FoldLatest,
    FoldMax,
    FoldMin,
    FoldOp,
    FoldSum,
    FoldWindow,
    LifecycleDecl,
    LoopDef,
)

# =============================================================================
# 1. KDL AST Node Factory
# =============================================================================


def make_kdl_node(
    name: str,
    args: list[Any] | None = None,
    properties: dict[str, Any] | None = None,
    children: list[ckdl.Node] | None = None,
    type_annotation: str | None = None,
) -> ckdl.Node:
    """Construct a ckdl.Node instance with explicit fields."""
    node = ckdl.Node()
    node.name = name
    node.args = list(args) if args is not None else []
    node.properties = dict(properties) if properties is not None else {}
    node.children = list(children) if children is not None else []
    node.type_annotation = type_annotation
    return node


# =============================================================================
# 2. Identifiers & Scalar Values
# =============================================================================

# Characters suitable for bare KDL identifiers
BARE_ID_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"

# Sample unicode identifiers (Cyrillic, Greek, Japanese)
UNICODE_ID_SAMPLES = [
    "привет",
    "мир",
    "конфиг",
    "αριθμός",
    "設定",
    "データ",
    "node_0",
    "prop_key",
    "item_sub",
    "loop_def",
    "my_node",
    "section",
]

KDL_KEYWORDS = {
    "null",
    "true",
    "false",
    "nan",
    "inf",
    "-inf",
    "+inf",
    "#null",
    "#true",
    "#false",
}


def is_ambiguous_string(s: str) -> bool:
    """Filter out strings that would unquote/coerce into numbers or keywords in KDL."""
    if not s:
        return False
    if s.lower() in KDL_KEYWORDS:
        return True
    return s[0] in "0123456789-+." or s.startswith(("0x", "0b", "0o"))


def kdl_identifiers() -> st.SearchStrategy[str]:
    """Valid KDL identifiers for node names, property keys, and type annotations."""
    return st.one_of(
        st.sampled_from(UNICODE_ID_SAMPLES),
        st.from_regex(r"^[a-zA-Z_][a-zA-Z0-9_.-]{0,19}$", fullmatch=True),
    )


def kdl_strings() -> st.SearchStrategy[str]:
    """String values including unicode, whitespace, and quotes."""
    return st.text(
        alphabet=st.characters(
            blacklist_categories=("Cs", "Cc"),
            blacklist_characters=("\x00",),
        ),
        max_size=30,
    ).filter(lambda s: not is_ambiguous_string(s))


def kdl_integers() -> st.SearchStrategy[int]:
    """Integer scalar values covering edge boundaries and standard ranges."""
    return st.one_of(
        st.sampled_from([0, -0, 1, -1, 42, -42, 1000, -1000, 2**31 - 1, -(2**31)]),
        st.integers(min_value=-1000000, max_value=1000000),
    )


def kdl_floats() -> st.SearchStrategy[float]:
    """Float scalar values with exact decimal representations for roundtrip stability."""
    # Note: KDL float serialization outputs finite decimal text; restricting to
    # half-integers / exact decimals ensures byte-identical roundtripping.
    return st.integers(min_value=-2000, max_value=2000).map(lambda x: x / 2.0)


def kdl_booleans() -> st.SearchStrategy[bool]:
    """Boolean scalar values."""
    return st.booleans()


def kdl_nulls() -> st.SearchStrategy[None]:
    """Null (#null) scalar values represented by None."""
    return st.none()


def kdl_scalars() -> st.SearchStrategy[Any]:
    """Arbitrary scalar values supported as arguments and property values."""
    return st.one_of(
        kdl_strings(),
        kdl_integers(),
        kdl_floats(),
        kdl_booleans(),
        kdl_nulls(),
    )


# =============================================================================
# 3. KDL Node & Document Strategies
# =============================================================================


def kdl_nodes(*, max_depth: int = 3) -> st.SearchStrategy[ckdl.Node]:
    """Recursive strategy generating valid ckdl.Node AST instances."""
    leaf_nodes = st.builds(
        make_kdl_node,
        name=kdl_identifiers(),
        args=st.lists(kdl_scalars(), max_size=4),
        properties=st.dictionaries(kdl_identifiers(), kdl_scalars(), max_size=3),
        children=st.just([]),
        type_annotation=st.one_of(st.none(), kdl_identifiers()),
    )

    def extend_children(child_strat: st.SearchStrategy[ckdl.Node]) -> st.SearchStrategy[ckdl.Node]:
        return st.builds(
            make_kdl_node,
            name=kdl_identifiers(),
            args=st.lists(kdl_scalars(), max_size=3),
            properties=st.dictionaries(kdl_identifiers(), kdl_scalars(), max_size=3),
            children=st.lists(child_strat, max_size=3),
            type_annotation=st.one_of(st.none(), kdl_identifiers()),
        )

    return st.recursive(leaf_nodes, extend_children, max_leaves=max_depth * 3)


def kdl_documents(
    *,
    min_nodes: int = 0,
    max_nodes: int = 5,
    max_depth: int = 3,
) -> st.SearchStrategy[ckdl.Document]:
    """Strategy generating valid ckdl.Document instances containing 0..N nodes."""
    return st.lists(
        kdl_nodes(max_depth=max_depth),
        min_size=min_nodes,
        max_size=max_nodes,
    ).map(ckdl.Document)


# =============================================================================
# 4. Declarative LoopDef & Vertex Document Strategies
# =============================================================================

FOLD_KEYS = ["topic", "name", "id", "status", "category", "service"]
FOLD_FIELDS = ["value", "amount", "cpu", "latency", "count", "score"]


def fold_declarations() -> st.SearchStrategy[FoldDecl]:
    """Strategy generating valid FoldDecl AST nodes."""
    ops: st.SearchStrategy[FoldOp] = st.one_of(
        st.sampled_from(FOLD_KEYS).map(lambda k: FoldBy(key_field=k)),
        st.just(FoldCount()),
        st.just(FoldLatest()),
        st.sampled_from(FOLD_FIELDS).map(lambda f: FoldSum(field=f)),
        st.sampled_from(FOLD_FIELDS).map(lambda f: FoldMin(field=f)),
        st.sampled_from(FOLD_FIELDS).map(lambda f: FoldMax(field=f)),
        st.sampled_from(FOLD_FIELDS).map(lambda f: FoldAvg(field=f)),
        st.integers(min_value=1, max_value=100).map(lambda m: FoldCollect(max_items=m)),
        st.tuples(st.sampled_from(FOLD_FIELDS), st.integers(min_value=1, max_value=20)).map(
            lambda t: FoldWindow(field=t[0], size=t[1])
        ),
    )
    return st.tuples(st.sampled_from(["items", "metrics", "total", "stats", "recent"]), ops).map(
        lambda t: FoldDecl(target=t[0], op=t[1])
    )


def loop_definitions() -> st.SearchStrategy[LoopDef]:
    """Strategy generating valid declarative LoopDef AST instances."""
    folds_st = st.lists(fold_declarations(), min_size=1, max_size=4, unique_by=lambda f: f.target)

    boundary_st = st.one_of(
        st.none(),
        st.integers(min_value=1, max_value=1000).map(lambda c: BoundaryEvery(count=c)),
        st.integers(min_value=1, max_value=1000).map(lambda c: BoundaryAfter(count=c)),
        st.just(
            BoundaryWhen(
                kind="session",
                match=(("status", "closed"),),
                conditions=(BoundaryCondition(target="high", op=">=", value=80.0),),
            )
        ),
    )

    edge_st = st.one_of(
        st.none(),
        st.builds(
            EdgeDecl,
            field=st.sampled_from(["ref", "topic", "name", "user"]),
            target=st.sampled_from(["decision", "thread", "task", "person"]),
        ),
    )

    lifecycle_st = st.one_of(
        st.none(),
        st.builds(
            LifecycleDecl,
            field=st.sampled_from(["status", "state", "phase"]),
            active=st.just(("open", "in_progress")),
        ),
    )

    return st.builds(
        LoopDef,
        folds=folds_st.map(tuple),
        boundary=boundary_st,
        edge=edge_st,
        lifecycle=lifecycle_st,
    )


def vertex_documents() -> st.SearchStrategy[str]:
    """Strategy generating valid .vertex documents with comments, formatting, and loop kinds."""
    kind_names = ["decision", "thread", "metrics", "alerts", "audit"]

    def build_vertex(kinds_to_include: list[str]) -> str:
        lines = [
            "// Top-level document header",
            'name "test_vertex"',
            'store "store.db"',
            "",
            "// Declarative loops block",
            "loops {",
        ]
        for k in kinds_to_include:
            lines.append(f"  // Section for {k}")
            lines.append(f"  {k} {{")
            lines.append("    fold {")
            lines.append(f'      items "by" "{k}_id"')
            lines.append("    }")
            lines.append("  }")
        lines.extend([
            "}",
            "",
            "// Observers block",
            "observers {",
            "  kyle {",
            '    key "AAAA"',
            "  }",
            "}",
            "",
        ])
        return "\n".join(lines)

    return st.lists(
        st.sampled_from(kind_names), min_size=2, max_size=4, unique=True
    ).map(build_vertex)

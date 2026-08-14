"""Hypothesis strategies for store property-based tests.

Provides timestamps, fact IDs, payloads, facts, fact lists, addresses, and fold ops.
"""

from __future__ import annotations

from typing import Any

from atoms import (
    Address,
    Avg,
    Collect,
    Count,
    Fact,
    FoldOp,
    Latest,
    Max,
    Min,
    Sum,
    TopN,
    Upsert,
    Window,
)
from hypothesis import strategies as st

# =============================================================================
# 1. Timestamps
# =============================================================================

EDGE_TIMESTAMPS: list[float] = [
    0.0,
    -0.0,
    1.0,
    -1.0,
    1000.0,
    1700000000.0,
    1736942400.0,  # 2025-01-15T12:00:00 UTC (test_fact anchor)
    946684800.0,   # 2000-01-01T00:00:00 UTC
    -62135596800.0,  # year 0001
    -1000000000.0,  # backdated (far past)
    4102444800.0,  # 2100-01-01 (far future)
    253402300799.0,  # 9999-12-31 (far future)
    32503680000.0,  # year 3000
]

SUB_MS_ANCHORS: list[float] = [0.0, 1000.0, 1700000000.0, 1736942400.0]
SUB_MS_DELTAS: list[float] = [
    0.0,
    1e-6,
    2e-6,
    5e-6,
    1e-5,
    1e-4,
    5e-4,
    1e-3,
    -1e-6,
    -1e-5,
    -1e-4,
    -1e-3,
]

SUB_MS_TIMESTAMPS: list[float] = [
    anchor + delta for anchor in SUB_MS_ANCHORS for delta in SUB_MS_DELTAS
]


def timestamps() -> st.SearchStrategy[float]:
    """Floats/epoch times biased toward edge cases: ties, sub-ms diffs, epoch 0, far past/future."""
    return st.one_of(
        st.sampled_from(EDGE_TIMESTAMPS),
        st.sampled_from(SUB_MS_TIMESTAMPS),
        st.floats(
            min_value=-1e10,
            max_value=253402300799.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        st.integers(min_value=-1000000, max_value=2000000000).map(float),
    )


# =============================================================================
# 2. Fact IDs
# =============================================================================

CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

EDGE_FACT_IDS = [
    "0" * 26,
    "7" + "Z" * 25,
    "Z" * 26,
    "01TESTULID0000000000000000",
    "01TESTULID0000000000000001",
    "01TESTULID0000000000000002",
    "01TESTULID000000000000000Z",
    "01TESTULID0000000000000010",
    "01TESTULID00000000000000AA",
    "01TESTULID00000000000000AB",
    "01ARZ3NDEKTSV4RRFFQ69G5FA0",
    "01ARZ3NDEKTSV4RRFFQ69G5FA1",
]

ID_PREFIXES_24 = [
    "01TESTULID00000000000000",
    "01ARZ3NDEKTSV4RRFFQ69G5F",
    "01H000000000000000000000",
]

ID_PREFIXES_25 = [
    "01TESTULID000000000000000",
    "01ARZ3NDEKTSV4RRFFQ69G5FA",
    "01H0000000000000000000000",
]


def fact_ids() -> st.SearchStrategy[str]:
    """Valid unique identifiers (26-char ULIDs) including trailing-char diff pairs."""
    return st.one_of(
        st.sampled_from(EDGE_FACT_IDS),
        st.tuples(
            st.sampled_from(ID_PREFIXES_25),
            st.sampled_from(list(CROCKFORD_ALPHABET)),
        ).map(lambda pair: pair[0] + pair[1]),
        st.tuples(
            st.sampled_from(ID_PREFIXES_24),
            st.text(alphabet=CROCKFORD_ALPHABET, min_size=2, max_size=2),
        ).map(lambda pair: pair[0] + pair[1]),
        st.text(alphabet=CROCKFORD_ALPHABET, min_size=26, max_size=26),
    )


# =============================================================================
# 3. Payloads
# =============================================================================

FOLD_KEY_EDGE_VALUES: list[Any] = [
    0,
    "0",
    0.0,
    False,
    True,
    1,
    "1",
    1.0,
    "",
    None,
    "null",
    "00",
    "0.0",
    "false",
    "true",
    "None",
]

FOLD_KEY_NAMES: list[str] = [
    "topic",
    "name",
    "service",
    "key",
    "id",
    "k",
]

NON_FOLD_KEY_NAMES: list[str] = [
    "status",
    "count",
    "amount",
    "cpu",
    "latency",
    "value",
    "app",
    "user",
    "data",
    "meta",
    "x",
    "y",
    "0",
    "",
    "привет",
    "🔑",
]


def json_primitives() -> st.SearchStrategy[Any]:
    """Primitive JSON leaf values (hashable scalars)."""
    return st.one_of(
        st.sampled_from(FOLD_KEY_EDGE_VALUES),
        st.booleans(),
        st.integers(min_value=-100000, max_value=100000),
        st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
        st.text(max_size=30),
        st.none(),
    )


def json_keys() -> st.SearchStrategy[str]:
    """JSON object keys."""
    return st.one_of(
        st.sampled_from(NON_FOLD_KEY_NAMES),
        st.text(max_size=20),
    )


def ref_strings() -> st.SearchStrategy[str]:
    """Comma-separated entity references for the reserved ref field."""
    return st.one_of(
        st.sampled_from(["", "decision/auth", "thread/main,task/1", "a,b,c", "k:v,k2:v2"]),
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_/:,", max_size=30),
    )


def payloads(
    *,
    min_size: int = 0,
    max_size: int = 8,
    include_fold_keys: bool = True,
) -> st.SearchStrategy[dict[str, Any]]:
    """JSON-object payloads with fold-key edge cases (0, '0', 0.0, False), unicode, nested data."""
    json_leaves = json_primitives()
    json_nodes = st.recursive(
        json_leaves,
        lambda children: st.one_of(
            st.lists(children, max_size=4),
            st.dictionaries(json_keys(), children, max_size=4),
        ),
        max_leaves=12,
    )
    general_dict = st.dictionaries(json_keys(), json_nodes, min_size=0, max_size=max_size)

    ref_dict = st.dictionaries(
        st.sampled_from(["ref"]),
        ref_strings(),
        min_size=0,
        max_size=1,
    )

    if include_fold_keys:
        fold_key_dict = st.dictionaries(
            st.sampled_from(FOLD_KEY_NAMES),
            json_leaves,
            min_size=0,
            max_size=len(FOLD_KEY_NAMES),
        )
        return st.tuples(general_dict, ref_dict, fold_key_dict).map(
            lambda t: {**t[0], **t[1], **t[2]}
        )

    return st.tuples(general_dict, ref_dict).map(lambda t: {**t[0], **t[1]})


# =============================================================================
# 4. Facts
# =============================================================================

COMMON_KINDS = [
    "heartbeat",
    "deploy",
    "tick.hourly",
    "tick.daily",
    "decision",
    "thread",
    "task",
    "system",
    "metric",
    "event",
    "log",
    "test",
]

COMMON_OBSERVERS = [
    "alice",
    "bob",
    "monitor",
    "sensor",
    "siftd",
    "v1",
    "system",
    "",
]

COMMON_ORIGINS = [
    "",
    "vertex-a",
    "vertex-b",
    "loop-a",
    "my-vertex",
]


def kinds() -> st.SearchStrategy[str]:
    """Fact kind strings."""
    return st.one_of(
        st.sampled_from(COMMON_KINDS),
        st.text(
            alphabet=st.characters(blacklist_categories=("Cs",)),
            min_size=1,
            max_size=30,
        ),
    )


def observers() -> st.SearchStrategy[str]:
    """Fact observer strings."""
    return st.one_of(
        st.sampled_from(COMMON_OBSERVERS),
        st.text(max_size=30),
    )


def origins() -> st.SearchStrategy[str]:
    """Fact origin strings."""
    return st.one_of(
        st.sampled_from(COMMON_ORIGINS),
        st.text(max_size=30),
    )


def facts(
    *,
    kind: st.SearchStrategy[str] | None = None,
    ts: st.SearchStrategy[float] | None = None,
    payload: st.SearchStrategy[Any] | None = None,
    observer: st.SearchStrategy[str] | None = None,
    origin: st.SearchStrategy[str] | None = None,
) -> st.SearchStrategy[Fact]:
    """Complete valid Fact values composed from timestamps, payloads, kinds, observers, origins."""
    kind_st = kind if kind is not None else kinds()
    ts_st = ts if ts is not None else timestamps()
    payload_st = payload if payload is not None else payloads()
    observer_st = observer if observer is not None else observers()
    origin_st = origin if origin is not None else origins()

    return st.builds(
        Fact,
        kind=kind_st,
        ts=ts_st,
        payload=payload_st,
        observer=observer_st,
        origin=origin_st,
    )


# =============================================================================
# 5. Fact Lists
# =============================================================================


def fact_lists(
    *,
    min_size: int = 0,
    max_size: int = 20,
    kind: st.SearchStrategy[str] | None = None,
) -> st.SearchStrategy[list[Fact]]:
    """Lists of facts with freely colliding timestamps (models store history)."""
    return st.lists(
        facts(kind=kind),
        min_size=min_size,
        max_size=max_size,
    )


def fact_and_id_lists(
    *,
    min_size: int = 0,
    max_size: int = 20,
    kind: st.SearchStrategy[str] | None = None,
) -> st.SearchStrategy[list[tuple[str, Fact]]]:
    """Lists of (fact_id, fact) pairs with DISTINCT IDs but freely colliding timestamps."""
    return st.integers(min_value=min_size, max_value=max_size).flatmap(
        lambda n: st.tuples(
            st.lists(fact_ids(), min_size=n, max_size=n, unique=True),
            st.lists(facts(kind=kind), min_size=n, max_size=n),
        ).map(lambda pair: list(zip(pair[0], pair[1], strict=True)))
    )


# =============================================================================
# 6. Additional Atoms Strategies
# =============================================================================


def addresses() -> st.SearchStrategy[Address]:
    """Entity references (Address objects)."""
    kind_st = st.one_of(
        st.sampled_from(["decision", "thread", "task", "person", ""]),
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz", max_size=15),
    )
    key_st = st.one_of(
        st.sampled_from(["auth", "storage", "engine", "design/foo", "design:foo"]),
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=20),
    )
    return st.builds(Address, kind=kind_st, key=key_st)


def fold_ops() -> st.SearchStrategy[FoldOp]:
    """Arbitrary valid fold operations."""
    return st.one_of(
        st.builds(Latest, target=st.sampled_from(["last_ts", "updated", "seen"])),
        st.builds(Count, target=st.sampled_from(["n", "count", "events"])),
        st.builds(
            Sum,
            target=st.sampled_from(["total", "sum_amt"]),
            field=st.sampled_from(["amount", "val", "x"]),
        ),
        st.builds(
            Collect,
            target=st.sampled_from(["items", "history", "records"]),
            max=st.integers(min_value=0, max_value=10),
        ),
        st.builds(
            Upsert,
            target=st.sampled_from(["users", "entities", "state"]),
            key=st.sampled_from(["id", "topic", "name", "key", "k"]),
        ),
        st.builds(
            TopN,
            target=st.sampled_from(["top", "leaders"]),
            key=st.sampled_from(["id", "name", "pid"]),
            by=st.sampled_from(["cpu", "score", "amount"]),
            n=st.integers(min_value=1, max_value=5),
            desc=st.booleans(),
        ),
        st.builds(
            Min,
            target=st.sampled_from(["min_v", "coldest"]),
            field=st.sampled_from(["temp", "val", "score"]),
        ),
        st.builds(
            Max,
            target=st.sampled_from(["max_v", "peak"]),
            field=st.sampled_from(["temp", "val", "score"]),
        ),
        st.builds(
            Avg,
            target=st.sampled_from(["avg_v", "rate"]),
            field=st.sampled_from(["latency", "val", "score"]),
        ),
        st.builds(
            Window,
            target=st.sampled_from(["window", "recent"]),
            field=st.sampled_from(["val", "interval", "latency"]),
            size=st.integers(min_value=1, max_value=10),
        ),
    )

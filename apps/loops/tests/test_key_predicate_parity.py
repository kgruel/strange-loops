"""Ratchet: fetch._item_matches_key and surface._row_matches_key must agree.

The --status honesty census (cli/dispatch._status_field_census) narrows its
input with fetch's ``_item_matches_key``, while the Surface's comma-OR
``--key`` filter narrows the rendered rows with ``surface._row_matches_key``
— near-twin predicates whose agreement is load-bearing for an exit code
(finding:chw-sol-r1-s1-f1-comma-key-census: a census over rows the Surface
filter would drop can flip a refusal into a plausible-empty exit 0).

This is the enumerable-property form of that invariant (simplify pass,
item 9): a matrix of key patterns x row shapes, asserting the two
predicates answer identically on every cell. If they ever legitimately
diverge, this test forces the divergence to be explicit — shrink the
matrix or split the predicates knowingly, never silently.

Scope note: both callers split comma-OR into single patterns BEFORE calling
the predicate (`--key a/,b/` becomes two calls), so a comma inside a
pattern here is a LITERAL key character, not an OR at this level.

Known out-of-matrix corner (documented, deliberately excluded): a FALSY
non-string fold-key value under a key_field that is NOT one of the label
fields (e.g. key_field="custom", payload={"custom": 0}) diverges today —
``_row_key``'s truthiness gate nulls Row.key while ``_item_matches_key``
still scans the field. Unreachable through the declared-fold pipeline the
census and Surface both ride; widening the matrix there means first
deciding which predicate is right, not just pinning agreement.
"""
from atoms.fold_state import FoldItem

from loops.commands.fetch import _item_matches_key
from loops.surface import Row, _row_key, _row_matches_key


# Row shapes: (key_field, payload). Covers declared fold keys, the
# label-field fallback chain (topic/name/title/summary), collect-folds
# (key_field=None), falsy/absent keys, unicode, and non-string values.
_ROW_SHAPES = [
    ("topic", {"topic": "design/foo", "message": "x"}),
    ("topic", {"topic": "Design/Foo"}),                    # case folding
    ("name", {"name": "arc-name", "status": "open"}),
    ("name", {"name": "reconcile-2026-08-12"}),
    ("topic", {"topic": "a,b"}),                           # literal comma key
    ("topic", {"name": "fallback-label"}),                 # key field absent
    ("topic", {"topic": "", "name": "empty-key-label"}),   # falsy fold value
    ("topic", {"topic": 0, "name": "zero-key"}),           # falsy non-string
    ("topic", {"topic": 42}),                              # non-string key
    ("custom", {"custom": "custom-keyed", "title": "t"}),  # non-label key field
    (None, {"name": "collect-labeled"}),                   # collect-fold
    (None, {"message": "no label fields at all"}),
    ("topic", {"topic": "καλημέρα/κόσμε"}),                # unicode
    ("topic", {"topic": "ΚΑΛΗΜΈΡΑ/κόσμε"}),                # unicode case fold
    ("name", {"name": "practice/scope", "summary": "s", "title": "t"}),
]

# Single pattern tokens (post comma-OR split — see module docstring).
_KEY_PATTERNS = [
    "design/",
    "design/foo",
    "DESIGN/FOO",
    "arc",
    "arc-name",
    "reconcile-",
    "a,b",          # literal comma
    "a,",
    "",             # empty pattern: startswith("") is True — both must agree
    "fallback",
    "empty",
    "zero",
    "4",
    "custom-",
    "collect",
    "no label",
    "καλημέρα/",
    "ΚΑΛΗΜΈΡΑ",
    "t",
    "absent-everywhere",
]


def _pair(key_field, payload):
    """One (FoldItem, Row) pair the way fetch and project produce them.

    The Row's ``key`` comes from the SAME derivation ``surface.project``
    uses (``_row_key``) so the pairing mirrors the production pipeline,
    not a hand re-derivation.
    """
    item = FoldItem(payload=dict(payload))
    key = _row_key(item, key_field)
    row = Row(
        address=f"k/{key or 'x'}",
        kind="k",
        key=key,
        key_field=key_field,
        payload=dict(payload),
    )
    return item, row


def test_item_and_row_key_predicates_agree_on_every_cell():
    disagreements = []
    for key_field, payload in _ROW_SHAPES:
        item, row = _pair(key_field, payload)
        for pattern in _KEY_PATTERNS:
            item_says = _item_matches_key(item, key_field, pattern)
            row_says = _row_matches_key(row, pattern)
            if item_says != row_says:
                disagreements.append(
                    f"key_field={key_field!r} payload={payload!r} "
                    f"pattern={pattern!r}: item={item_says} row={row_says}"
                )
    assert not disagreements, (
        "fetch._item_matches_key and surface._row_matches_key disagree — "
        "the --status census and the Surface --key filter no longer see the "
        "same rows (exit-code-bearing; see module docstring):\n"
        + "\n".join(disagreements)
    )

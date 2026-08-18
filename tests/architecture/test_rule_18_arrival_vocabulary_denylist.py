"""Rule 18: the arrival surface never names the superseded vocabulary."""

from __future__ import annotations

import ast
import re

import pytest

from ._helpers import REPO_ROOT

# The ratified glossary (decision:design/arrival-slice0-record-grammar §4.1)
# is small on purpose: arrival log, record, lineage, ordinal, coordinate,
# genesis, head, append, resume mark, torn tail, projection, body. §4.2
# ratifies a seed denylist alongside it — terms from the model the arrival
# substrate replaces. They are banned here because a name is how a retired
# model gets rebuilt in the next reader's head: the resume mark is
# `arrival_*` rather than a rename of the old meta keys precisely because
# renaming would have carried the two row counts along, and starting from the
# arrival axis is what showed they dissolve.
#
# Scope note (deliberately narrow — "scope the claim before widening the
# detection"). This judges the ARRIVAL surface only: the arrival module and
# every shipped source file under `libs/sdk/src`, which the design fact names
# as the eventual public surface. Legacy modules keep their vocabulary until
# their own cuts dissolve them — scanning them would turn this rule into a
# standing failure that gets suppressed rather than a gate that holds. When a
# later slice moves custody into a module, that module joins _SCAN_TARGETS in
# the same change. Tests are out of scope for the same reason Rule 17 excludes
# them: a test states the banned vocabulary in order to assert it is gone, and
# folding those into an allowlist dilutes it.

# Paths, relative to the repo root, whose names are held to the arrival
# glossary. GROW as arrival slices land; never shrink to make a failure go
# away.
_SCAN_TARGETS = (
    "libs/engine/src/engine/arrival.py",
    "libs/sdk/src",
)

# The seed denylist, §4.2, spelled in canonical snake_case (see _denied_term).
_DENIED = {
    "jsonl_canonical": "the retired canonical-store name",
    "jsonl_offset": "the retired offset meta key",
    "jsonl_fact_count": "the retired count meta key",
    "jsonl_tick_count": "the retired count meta key",
    "receipt_order": "ordering is by ordinal, not by an order concept",
    "receipt_mode": "there is no mode — custody is structural, not configured",
    "reanchor": "not an operation in the arrival model",
    "rewind": "not an operation in the arrival model",
    "mergeability": "not a property of custody",
    "union_discipline": "not a property of custody",
}

# What §4.2 bans that this rule deliberately does NOT (review round 1, F3).
# The list also retires "event as an ordering concept", "merge as something
# that touches custody", and "receipt as an ordering or custody concept" —
# each qualified by the SENSE the word is used in. A token scanner cannot
# read sense, so banning the bare words would be a verdict claim ("this
# usage is the retired concept") where the evidence only supports a location
# claim. It would also fire on `libs/sdk`'s `EmitReceipt`, which is a
# write-result record and has nothing to do with custody ordering. The
# qualified bans stay a review responsibility; this rule holds the
# unambiguous ones. Named here so the gap reads as scoped, not missed.
_NOT_MECHANIZED = ("event", "merge", "receipt")

# camelCase and PascalCase boundaries. Both forms, so `JsonlOffset`,
# `jsonlOffset` and `HTTPRewind` all split into the tokens they are made of —
# case was the first evasion the reviewer found, and a scanner that only
# matches the snake_case spelling is a scanner that bans one way of writing
# the word.
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NAME_SEP = re.compile(r"[-_]+")
_PROSE_SEP = re.compile(r"[^a-z0-9_]+")

# Denied terms, separators removed, mapped back to their canonical spelling.
# Comparing squashed lets `ReAnchor` (which camel-splits into `re` + `anchor`)
# land on `reanchor`, without a substring test that would make `rewinding`
# match `rewind`.
_SQUASHED = {term.replace("_", ""): term for term in _DENIED}
_MAX_TOKENS = 4  # longest denied term is 3 tokens; camel splitting can add one


def _name_segments(text: str) -> list[list[str]]:
    """Split ``text`` into runs of tokens that a single NAME could span.

    Two kinds of separator, kept apart on purpose. Underscores, hyphens and
    camelCase boundaries join tokens INTO one name, so `union_discipline`,
    `union-discipline` and `UnionDiscipline` are all one segment of two
    tokens. Whitespace and punctuation separate names from each other, so
    they end a segment.

    That distinction is what keeps a multi-word ban an IDENTIFIER ban. §4.2
    bans these as "identifiers, meta keys, field names, function names, or
    glossary terms" — matching `receipt_order` across a space would also
    condemn the sentence "for a single-store vertex this is receipt order",
    which is `libs/sdk`'s honest description of today's shipped behaviour and
    is Rule 17's territory, not this rule's. Single-token bans still match in
    prose: one word is unambiguous, a two-word phrase is not.
    """
    lowered = _CAMEL.sub("_", text).lower()
    joined = _NAME_SEP.sub("_", lowered)
    return [
        [token for token in segment.split("_") if token]
        for segment in _PROSE_SEP.sub(" ", joined).split()
    ]


def _denied_term(text: str) -> str | None:
    """The denied term ``text`` names, or None."""
    for tokens in _name_segments(text):
        for start in range(len(tokens)):
            for end in range(start + 1, min(start + _MAX_TOKENS, len(tokens)) + 1):
                term = _SQUASHED.get("".join(tokens[start:end]))
                if term is not None:
                    return term
    return None


# ---------------------------------------------------------------------------
# Allowlist — SHRINK ONLY.
#
# Entries are (path relative to repo root, a substring that must appear on the
# offending line). Content markers, not line numbers: code moves, and a
# line-numbered allowlist churns on every unrelated edit while silently
# re-admitting a moved claim. Empty today, and an entry added here needs a
# comment saying why the term is unavoidable at that site.
# ---------------------------------------------------------------------------
_ALLOWED: set[tuple[str, str]] = set()


def _files() -> list:
    """Every shipped file the rule judges, derived from _SCAN_TARGETS.

    A directory target expands to its `.py` files; a file target is itself.
    Derived rather than hand-enumerated (docs/RATCHETS.md), so a module added
    under `libs/sdk/src` after this was written is judged the moment it
    exists.
    """
    files = []
    for target in _SCAN_TARGETS:
        path = REPO_ROOT / target
        if path.is_dir():
            files.extend(
                p for p in sorted(path.rglob("*.py")) if "__pycache__" not in p.parts
            )
        elif path.is_file():
            files.append(path)
    return files


def _named(tree: ast.AST) -> list[tuple[int, str]]:
    """Every (lineno, text) this rule judges: things that NAME something.

    In scope: identifiers (variables, attributes, arguments, functions,
    classes, import aliases, keyword-argument names), docstrings, and string
    constants used as **keys** — a dict key and a subscript index are naming a
    field just as surely as an attribute is, which is how the reviewer's
    `{'jsonl_offset': ...}` evasion got past the first cut.

    Out of scope, and deliberately: comments, and string constants that are
    not keys. That is the scoped claim — this rule asserts the arrival
    surface does not NAME the retired vocabulary, not that the words never
    appear. A comment saying "this replaces the old offset meta key" is
    honest documentation of a boundary; an identifier spelling it is the
    model coming back.
    """
    judged: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            judged.append((node.lineno, node.id))
        elif isinstance(node, ast.Attribute):
            judged.append((node.lineno, node.attr))
        elif isinstance(node, ast.arg):
            judged.append((node.lineno, node.arg))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            judged.append((node.lineno, node.name))
            doc = ast.get_docstring(node, clean=False)
            if doc:
                judged.append((node.lineno, doc))
        elif isinstance(node, ast.Module):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                judged.append((1, doc))
        elif isinstance(node, ast.alias):
            judged.append((getattr(node, "lineno", 1), node.asname or node.name))
        elif isinstance(node, ast.keyword) and node.arg:
            judged.append((node.value.lineno, node.arg))
        elif isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    judged.append((key.lineno, key.value))
        elif isinstance(node, ast.Subscript):
            index = node.slice
            if isinstance(index, ast.Constant) and isinstance(index.value, str):
                judged.append((index.lineno, index.value))
    return judged


def _faults(source: str, rel: str) -> list[str]:
    """Every denied name in one file's source, as reportable lines.

    The production scan and the evasion probes below run through this one
    function, so a probe cannot pass against a code path the real scan does
    not use.
    """
    lines = source.splitlines()
    found: list[str] = []
    for lineno, text in _named(ast.parse(source, filename=rel)):
        term = _denied_term(text)
        if term is None:
            continue
        line = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
        if any(rel == p and marker in line for p, marker in _ALLOWED):
            continue
        found.append(f"{rel}:{lineno}: {term!r} — {_DENIED[term]}")
    return found


def test_scan_targets_all_exist():
    """A target that has moved silently stops being judged."""
    missing = [t for t in _SCAN_TARGETS if not (REPO_ROOT / t).exists()]
    assert not missing, f"Rule 18 scans paths that no longer exist: {missing}"


def test_allowlist_entries_still_apply():
    """Stale allowlist entries must be cleaned up, not left as cover."""
    for path, marker in _ALLOWED:
        full = REPO_ROOT / path
        assert full.exists(), f"Stale allowlist entry: {path} no longer exists"
        assert marker in full.read_text(), (
            f"Stale allowlist entry: {path} no longer contains {marker!r}"
        )


def test_the_arrival_surface_never_names_the_denied_vocabulary():
    found: list[str] = []
    for path in _files():
        rel = str(path.relative_to(REPO_ROOT))
        found.extend(_faults(path.read_text(), rel))

    assert not found, (
        "The arrival surface names vocabulary the arrival model retired "
        "(decision:design/arrival-slice0-record-grammar §4.2). Rename to the "
        "ratified glossary; do not add an allowlist entry unless the term is "
        "genuinely unavoidable at that site:\n  " + "\n  ".join(sorted(found))
    )


# ---------------------------------------------------------------------------
# Evasion probes — review round 1, F3.
#
# Every one of these got past the first cut of this rule. They are test cases
# now so the detector cannot quietly regress to matching one spelling of a
# word, which is the failure mode a denylist has.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, term",
    [
        # The four the reviewer found.
        ("JsonlOffset = 1\n", "jsonl_offset"),
        ("RECEIPT_ORDER = 1\n", "receipt_order"),
        ("def Rewind():\n    pass\n", "rewind"),
        ("X = {'jsonl_offset': 1}\n", "jsonl_offset"),
        # The pair that was missing from the denylist entirely.
        ("union_discipline = 1\n", "union_discipline"),
        ("X = {'union-discipline': 1}\n", "union_discipline"),
        # Same shapes, generalized — the point is the spelling, not the term.
        ("jsonlOffset = 1\n", "jsonl_offset"),
        ("class ReAnchor:\n    pass\n", "reanchor"),
        ("def f(Mergeability=None):\n    pass\n", "mergeability"),
        ("record['RECEIPT_MODE'] = 1\n", "receipt_mode"),
        ('def f():\n    """We rewind the log here."""\n', "rewind"),
        ("UnionDiscipline = 1\n", "union_discipline"),
    ],
)
def test_the_detector_catches_known_evasions(source, term):
    faults = _faults(source, "probe.py")
    assert faults, f"evasion not caught: {source!r}"
    assert term in faults[0], f"caught as the wrong term: {faults[0]}"


@pytest.mark.parametrize(
    "source",
    [
        # The ratified glossary itself must never trip the rule.
        "arrival_offset = 1\narrival_ordinal = 2\narrival_lineage = 'x'\n",
        "def record_hash(record):\n    return record['rh']\n",
        "prev = None\nordinal = 0\ncoordinate = (lineage, ordinal)\n",
        # Comments are out of scope by design — see _named.
        "# jsonl_offset is the retired meta key this replaces\nx = 1\n",
        # A denied term inside a longer word is a different word.
        "rewinding = 0\nprewind = 1\n",
        # A multi-word ban is an IDENTIFIER ban: the same two words separated
        # by a space are prose, and prose is Rule 17's territory. This exact
        # sentence is libs/sdk's honest description of shipped behaviour.
        'def f():\n    """For a single-store vertex this is receipt order."""\n',
        # sdk's EmitReceipt: `receipt` alone is not mechanized (_NOT_MECHANIZED).
        "class EmitReceipt:\n    pass\n",
    ],
)
def test_the_detector_does_not_fire_on_the_ratified_glossary(source):
    assert _faults(source, "probe.py") == []


def test_the_unmechanized_bans_are_named_rather_than_silently_dropped():
    """§4.2 bans more than this rule mechanizes. The gap is documented, and
    this asserts the documentation stays honest — a term must not drift into
    _DENIED as a bare word without the sense qualification being resolved."""
    for word in _NOT_MECHANIZED:
        assert word not in _DENIED, (
            f"{word!r} is a sense-qualified ban in §4.2; mechanizing it bare "
            "makes this rule a verdict claim rather than a location claim"
        )

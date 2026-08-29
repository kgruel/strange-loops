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
# away. Cut A moved custody into the funnel (residence, probe) and built the
# arrival write path (arrival_store — a new module born on the arrival
# surface, so it joins at birth).
#
# Cut B adds four. `arrival_projection` and `derived_log_merge` are NEW and
# born on the arrival surface, so they join at birth. `store/merge.py` and
# `store/receive.py` join because CUSTODY MOVED INTO THEM: they stopped being
# direct index writers and became arrival appenders, which is this rule's own
# stated trigger.
#
# `jsonl_store.py` does NOT join, departing from
# `plan:arrival-vocabulary-ratchet`'s "jsonl_store until cut B". Custody has
# not left it: it remains the write path for `.jsonl`-canonical stores, which
# survive until the sidecar/CLI-rebuild tail, and its `jsonl_offset` /
# `jsonl_fact_count` / `jsonl_tick_count` names are that mode's HONEST keys.
# Adding it here would produce a standing failure resolvable only by a large
# allowlist — the outcome the scope note below warns against. Its cut is the
# one that retires `JsonlStore`.
_SCAN_TARGETS = (
    "libs/engine/src/engine/arrival.py",
    # Wire v1 (slice 1) forked the arrival body encoding out of the legacy
    # line codec. `arrival_body` is NEW and born on the arrival surface, so
    # it joins at birth — the same trigger `arrival_projection` joined on.
    # `jsonl_codec` does NOT join and will not: it is the legacy framing by
    # definition, kept for the derived-log projection and the migration
    # sidecar, and its vocabulary is that mode's honest vocabulary.
    "libs/engine/src/engine/arrival_body.py",
    "libs/engine/src/engine/arrival_projection.py",
    "libs/engine/src/engine/arrival_store.py",
    "libs/engine/src/engine/probe.py",
    "libs/engine/src/engine/residence.py",
    "libs/sdk/src",
    "libs/store/src/store/derived_log_merge.py",
    "libs/store/src/store/merge.py",
    "libs/store/src/store/receive.py",
)

# The seed denylist, §4.2, spelled in canonical snake_case (see _denied_term).
_DENIED = {
    "jsonl_canonical": "the retired canonical-store name",
    "jsonl_offset": "the retired offset meta key",
    "jsonl_fact_count": "the retired count meta key",
    "jsonl_tick_count": "the retired count meta key",
    "receipt_order": "ordering is by ordinal, not by an order concept",
    # Added at cut B, which retires the R1 doctrine whose vocabulary was "the
    # merged store's fold order". After B the ordering claim is the arrival
    # ordinal, so `fold_order` as an identifier on the arrival surface is the
    # retired model coming back. Unambiguous and single-concept, so it
    # mechanizes exactly the way `receipt_order` already does.
    "fold_order": "the ordering claim is the arrival ordinal, not a fold order",
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
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Denied terms, separators removed, mapped back to their canonical spelling.
# Comparing squashed lets `ReAnchor` (which camel-splits into `re` + `anchor`)
# land on `reanchor`, without a substring test that would make `rewinding`
# match `rewind`.
_SQUASHED = {term.replace("_", ""): term for term in _DENIED}
_MAX_TOKENS = 4  # longest denied term is 3 tokens; camel splitting can add one


NAME = "name"
PROSE = "prose"


def _name_segments(text: str, mode: str) -> list[list[str]]:
    """Split ``text`` into runs of tokens that a single NAME could span.

    Two kinds of separator, and which is which depends on what the text IS.

    In ``NAME`` mode the whole string is one name, so every separator joins:
    `jsonl.offset`, `jsonl-offset`, `jsonl_offset` and `JsonlOffset` are the
    same name written four ways. This is the mode for identifiers and for
    strings that sit in identifier positions — a dict key, a subscript
    index, an ``__all__`` entry, a string annotation.

    In ``PROSE`` mode — docstrings — underscores, hyphens and camelCase still
    join, but whitespace and punctuation end a segment, because they separate
    names from each other rather than building one. That distinction is what
    keeps a multi-word ban an IDENTIFIER ban. §4.2 bans these as
    "identifiers, meta keys, field names, function names, or glossary terms";
    matching `receipt_order` across a space would also condemn the sentence
    "for a single-store vertex this is receipt order", which is `libs/sdk`'s
    honest description of today's shipped behaviour and is Rule 17's
    territory, not this rule's. Single-token bans still match in prose: one
    word is unambiguous, a two-word phrase is not.
    """
    lowered = _CAMEL.sub("_", text).lower()
    if mode == NAME:
        return [[token for token in _NON_ALNUM.sub("_", lowered).split("_") if token]]
    joined = _NAME_SEP.sub("_", lowered)
    return [
        [token for token in segment.split("_") if token]
        for segment in _PROSE_SEP.sub(" ", joined).split()
    ]


def _denied_term(text: str, mode: str = NAME) -> str | None:
    """The denied term ``text`` names, or None."""
    for tokens in _name_segments(text, mode):
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
_ALLOWED: set[tuple[str, str]] = {
    # The retired canonical-store boolean survives as an unexported shim for
    # ONE caller: apps/loops/src/loops/commands/store.py:142 lazy-imports it
    # before its mode check, and apps/ is diff-empty for the whole arrival
    # wave, so the caller cannot move until the CLI-surface cut. The shim is
    # not in residence.__all__, nothing else in libs names it, and
    # tests/engine's tripwire pins the pairing — delete this entry together
    # with the shim and the apps import.
    ("libs/engine/src/engine/residence.py", "def is_jsonl_canonical"),
    # The refusing override of the legacy history-mutating op must carry the
    # legacy METHOD name or it overrides nothing — the name here IS the
    # refusal surface. Falls away when the base method retires.
    ("libs/engine/src/engine/arrival_store.py", "def reanchor"),
    # The legacy mode's own exception family, raised where a merge into a
    # `.jsonl`-canonical target is refused. The name IS that mode's honest
    # name — the same reasoning that keeps its three meta keys unrenamed —
    # and merge.py must NAME the class to raise it. Aliasing the import
    # would silence this rule while changing nothing, which is precisely the
    # evasion the probes below exist to catch. Falls away when `JsonlStore`
    # retires and the refusal has nothing left to point at.
    ("libs/store/src/store/merge.py", "raise jsonl_store.JsonlCanonicalUnsupported("),
}


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


def _strings_in(node: ast.AST | None) -> list[tuple[int, str]]:
    """Every string constant inside a subtree, with its line.

    Used for the two places a NAME can hide inside a string: a forward-ref
    annotation (``def f(x: "JsonlOffset")``) and an ``__all__`` entry.
    """
    if node is None:
        return []
    return [
        (child.lineno, child.value)
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    ]


def _is_dunder_all(target: ast.expr) -> bool:
    return isinstance(target, ast.Name) and target.id == "__all__"


def _named(tree: ast.AST) -> list[tuple[int, str, str]]:
    """Every (lineno, text, mode) this rule judges: things that NAME something.

    In scope, all in ``NAME`` mode unless noted: identifiers (variables,
    attributes, arguments, functions, classes, import aliases,
    keyword-argument names); docstrings (``PROSE`` mode); and string
    constants sitting in identifier positions —

    * **dict keys and subscript indices**, because a key names a field just
      as surely as an attribute does;
    * **``__all__`` entries**, because an export list is naming, and it is
      the most public naming a module does;
    * **annotations**, including string forward references, because a
      forward ref is an identifier the parser has not resolved yet.

    Out of scope, and deliberately: comments, and string constants that are
    not in one of those positions. That is the scoped claim — this rule
    asserts the arrival surface does not NAME the retired vocabulary, not
    that the words never appear. A comment saying "this replaces the old
    offset meta key" is honest documentation of a boundary; an identifier
    spelling it is the model coming back.

    Also out of scope, named rather than discovered: ``__all__`` built by
    call rather than by literal (``__all__.extend([...])``,
    ``__all__ = list(...)``). Following those means evaluating the program,
    which is the whole-program analysis a ratchet must not become. A repo
    that starts building exports that way needs this list grown, and the
    scan-target test is what will surface it.

    Known-unscanned node types, listed so a future reader can see they were
    considered rather than missed: dict-comprehension keys, ``except ... as``
    names, and ``match`` capture patterns. Each could in principle carry a
    denied name. None is widened for now because the shipped code does not
    use those forms for retired vocabulary, and growing a detector without a
    forcing case is the move this repo's practice warns against — the
    detector would gain surface with nothing holding it honest. Any of them
    becomes worth adding the day a real usage appears.
    """
    judged: list[tuple[int, str, str]] = []

    def name(lineno: int, text: str) -> None:
        judged.append((lineno, text, NAME))

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            name(node.lineno, node.id)
        elif isinstance(node, ast.Attribute):
            name(node.lineno, node.attr)
        elif isinstance(node, ast.arg):
            name(node.lineno, node.arg)
            for lineno, text in _strings_in(node.annotation):
                name(lineno, text)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name(node.lineno, node.name)
            doc = ast.get_docstring(node, clean=False)
            if doc:
                judged.append((node.lineno, doc, PROSE))
            for lineno, text in _strings_in(getattr(node, "returns", None)):
                name(lineno, text)
        elif isinstance(node, ast.Module):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                judged.append((1, doc, PROSE))
        elif isinstance(node, ast.alias):
            name(getattr(node, "lineno", 1), node.asname or node.name)
        elif isinstance(node, ast.keyword) and node.arg:
            name(node.value.lineno, node.arg)
        elif isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    name(key.lineno, key.value)
        elif isinstance(node, ast.Subscript):
            index = node.slice
            if isinstance(index, ast.Constant) and isinstance(index.value, str):
                name(index.lineno, index.value)
        elif isinstance(node, ast.Assign):
            if any(_is_dunder_all(t) for t in node.targets):
                for lineno, text in _strings_in(node.value):
                    name(lineno, text)
        elif isinstance(node, ast.AugAssign):
            if _is_dunder_all(node.target):
                for lineno, text in _strings_in(node.value):
                    name(lineno, text)
        elif isinstance(node, ast.AnnAssign):
            for lineno, text in _strings_in(node.annotation):
                name(lineno, text)
            if _is_dunder_all(node.target):
                for lineno, text in _strings_in(node.value):
                    name(lineno, text)
    return judged


def _faults(source: str, rel: str) -> list[str]:
    """Every denied name in one file's source, as reportable lines.

    The production scan and the evasion probes below run through this one
    function, so a probe cannot pass against a code path the real scan does
    not use.
    """
    lines = source.splitlines()
    found: list[str] = []
    for lineno, text, mode in _named(ast.parse(source, filename=rel)):
        term = _denied_term(text, mode)
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
        # Round 2, F3-R2. An export list is naming, and it is the most
        # public naming a module does.
        ('__all__ = ["jsonl_offset"]\n', "jsonl_offset"),
        ('__all__ = ["a"]\n__all__ += ["Rewind"]\n', "rewind"),
        # A string forward reference is an identifier the parser has not
        # resolved yet.
        ('def f(x: "JsonlOffset"):\n    pass\n', "jsonl_offset"),
        ('def f() -> "ReAnchor":\n    pass\n', "reanchor"),
        ('x: "Mergeability" = None\n', "mergeability"),
        # In NAME mode every separator joins, so punctuation cannot split a
        # key out of reach the way it did before.
        ('X = {"jsonl.offset": 1}\n', "jsonl_offset"),
        ('X = {"union discipline": 1}\n', "union_discipline"),
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
        # Round 2 negative controls — the three new forms must not fire on
        # names libs/sdk legitimately uses.
        '__all__ = ["EmitReceipt", "ResumeMark"]\n',
        'def f(x: "ResumeMark") -> "EmitReceipt":\n    pass\n',
        'X = {"loops.sdk/emit-receipt/v1": 1}\n',
        'X = {"arrival.offset": 1, "arrival-ordinal": 2}\n',
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

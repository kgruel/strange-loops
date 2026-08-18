"""Rule 18: the arrival surface never spells the superseded vocabulary."""

from __future__ import annotations

import ast
import re

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

# Paths, relative to the repo root, whose identifiers and docstrings are held
# to the arrival glossary. GROW as arrival slices land; never shrink to make a
# failure go away.
_SCAN_TARGETS = (
    "libs/engine/src/engine/arrival.py",
    "libs/sdk/src",
)

# The seed denylist, §4.2. Word-boundary matched so `previous` does not trip
# on nothing and `unmerged` does trip: a substring ban would be noise, and a
# whole-word ban is what the glossary actually says.
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
}

_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(term) for term in sorted(_DENIED)) + r")\b"
)

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


def _scan_target_paths_all_exist() -> list[str]:
    return [t for t in _SCAN_TARGETS if not (REPO_ROOT / t).exists()]


def _named_and_documented(tree: ast.AST) -> list[tuple[int, str]]:
    """Every (lineno, text) this rule judges: identifiers and docstrings.

    Comments are NOT judged, and that is the scoped claim: this rule asserts
    that the arrival surface does not NAME the retired vocabulary, not that
    the words never appear. A comment saying "this replaces the old offset
    meta key" is honest documentation of a boundary; an identifier spelling
    it is the model coming back.
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
    return judged


def test_scan_targets_all_exist():
    """A target that has moved silently stops being judged."""
    missing = _scan_target_paths_all_exist()
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
        source = path.read_text()
        lines = source.splitlines()
        for lineno, text in _named_and_documented(ast.parse(source, filename=str(path))):
            match = _PATTERN.search(text)
            if match is None:
                continue
            line = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
            if any(rel == p and marker in line for p, marker in _ALLOWED):
                continue
            term = match.group(1)
            found.append(f"{rel}:{lineno}: {term!r} — {_DENIED[term]}")

    assert not found, (
        "The arrival surface names vocabulary the arrival model retired "
        "(decision:design/arrival-slice0-record-grammar §4.2). Rename to the "
        "ratified glossary; do not add an allowlist entry unless the term is "
        "genuinely unavoidable at that site:\n  " + "\n  ".join(sorted(found))
    )


def test_the_rule_can_see_a_violation():
    """The detector is not vacuous: a denied term in a docstring is caught."""
    tree = ast.parse('def f():\n    """rewind the log."""\n')
    judged = _named_and_documented(tree)
    assert any(_PATTERN.search(text) for _lineno, text in judged)

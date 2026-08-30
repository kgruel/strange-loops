"""Conformance runner for head comparison (witness-protocol.html §07).

Loads all vectors from ``spec/conformance/vectors/comparison/*.json`` the way
``test_conformance_replicate.py`` loads its three families — one glob, one
parametrize, the envelope asserted before the body, and an inventory that must
equal what is on disk in BOTH directions.

**Two vector forms, and the split is this area's design point.** ``form:
"heads"`` hands a ``(known, presented, at_known)`` triple straight to the pure
classifier, pinning the seven §07 rows with no journal encoding at all — §B.3's
journal is a local cache grammar, not wire, and no other implementation is
obliged to have one. ``form: "journal"`` hands raw lines to the pure reader and
then attempts the comparison, because every read rule (trust-epoch scoping, the
maximum-ordinal rule, equivocation, the incomplete-read lower bound, the
header's three-way classification) is unreachable from the classifier.

**Outcome strings, never exception types.** A vector names an outcome by its
ratified §07 string. The one place a vector must speak of a refusal — a journal
that equivocates — it names the READ STATE ``"equivocation"``, and the mapping
to this implementation's class lives in ``READ_REFUSALS`` here, exactly as
``test_conformance_replicate.py`` maps its two contract refusals. Naming a
Python exception family in a language-neutral vector would pin that family on
every other implementation.

**The outcome slot holds the seven ratified strings or null.** Null means
``established_head()`` refused and ``compare`` was never called, so there is no
outcome to state; ``expected.read`` carries why. Deliberately not an eighth
string: a normative vector carrying ``"declined"`` would read to a foreign
implementer as a value to return.

**Pure functions only, and that is what keeps the real state root untouched.**
This runner calls ``parse_journal_lines``, ``established_head`` and ``compare``
and nothing else — none of which resolves a path — so no test here can reach
``$XDG_STATE_HOME`` even if one is set. ``test_the_runner_stays_on_the_pure_surface``
pins it rather than leaving it to reviewer vigilance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from engine.arrival_contract import Head
from engine.arrival_head_attestation import (
    EstablishedHead,
    HeadAttestation,
    HeadLowerBound,
    HeadUnreadable,
    IndeterminateComparison,
    JournalEquivocation,
    Kind,
    Level,
    Outcome,
    compare,
    parse_journal_lines,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPARISON_VECTORS_DIR = (
    REPO_ROOT / "spec" / "conformance" / "vectors" / "comparison"
)

# The read states a vector may name, and the type each one claims. A state
# outside this mapping is a vector claiming something this area does not
# define, and KeyError says so loudly rather than skipping the vector green.
KNOWN_STATES: dict[str, type] = {
    "none": type(None),
    "established": EstablishedHead,
    "bounded": HeadLowerBound,
    "unreadable": HeadUnreadable,
}

# The one read state that is a refusal rather than a result. Mapped here, never
# in a vector, for the reason the replicate family gives.
READ_REFUSALS: dict[str, type[Exception]] = {"equivocation": JournalEquivocation}

# What a LOWER BOUND may soundly answer. ROLLBACK-ONLY, as ruled: a presented
# head below the bound is certainly below the accepted head, and nothing bounds
# the accepted head from above, so neither proceed row is obtainable. Held as
# an enumerable set so widening it is a visible edit to a ratified posture.
SOUND_ANSWERS: frozenset[str | None] = frozenset({None, "rollback"})

# The three families of the seven-row classifier and the four families of the
# read, and the EXACT vector inventory of each.
#
# Filenames rather than a count, and a count rather than "at least one": a
# family check that only asks whether the family is non-empty goes green when a
# fixture is deleted, right up until the last one goes.
#
# GROW this when a vector is added; shrink it only when a claim is genuinely
# retired, and say which in the commit.
VECTOR_INVENTORY: dict[str, frozenset[str]] = {
    "comparison-classify-": frozenset({
        "comparison-classify-first-contact",
        "comparison-classify-unchanged",
        "comparison-classify-advanced",
        "comparison-classify-rollback",
        "comparison-classify-same-height-fork",
        "comparison-classify-rewrite-at-the-known-ordinal",
        "comparison-classify-rewrite-when-the-ledger-vouches-for-nothing",
        "comparison-classify-lineage-replaced",
        "comparison-classify-lineage-replaced-outranks-a-lower-ordinal",
    }),
    "comparison-epoch-": frozenset({
        "comparison-epoch-ends-at-the-reset-entry-is-unchanged",
        "comparison-epoch-below-the-reset-head-is-rollback",
        "comparison-epoch-scopes-the-equivocation-check-too",
    }),
    "comparison-journal-": frozenset({
        "comparison-journal-the-known-head-is-the-maximum-ordinal",
        "comparison-journal-equivocation-refuses-the-read",
        "comparison-journal-agreeing-entries-at-the-maximum-are-not-equivocation",
        "comparison-journal-a-byte-identical-line-is-a-re-assertion",
        "comparison-journal-an-empty-journal-is-first-contact",
        "comparison-journal-a-header-only-journal-is-first-contact",
        "comparison-journal-unknown-fields-on-a-v1-entry-are-read",
    }),
    "comparison-incomplete-": frozenset({
        "comparison-incomplete-a-torn-line-yields-a-lower-bound",
        "comparison-incomplete-a-bound-still-refuses-below-itself",
        "comparison-incomplete-a-bound-cannot-answer-above-itself",
        "comparison-incomplete-a-headerless-journal-yields-a-bound",
        "comparison-incomplete-nothing-readable-declines-every-comparison",
        "comparison-incomplete-a-re-mint-against-lost-content-is-not-first-contact",
    }),
    "comparison-header-": frozenset({
        "comparison-header-a-kindless-object-is-not-absorbed",
        "comparison-header-both-markers-together-are-unclassifiable",
        "comparison-header-a-later-builds-header-is-still-a-header",
    }),
}


def _load_vectors(vectors_dir: Path) -> list[Path]:
    return sorted(vectors_dir.glob("*.json"))


def _head(data: dict[str, Any] | None) -> Head | None:
    if data is None:
        return None
    return Head(
        lineage=data["lineage"],
        ordinal=data["ordinal"],
        record_hash=data["record_hash"],
    )


def _entry(data: dict[str, Any] | None) -> HeadAttestation | None:
    if data is None:
        return None
    return HeadAttestation(
        head=Head(
            lineage=data["lineage"],
            ordinal=data["ordinal"],
            record_hash=data["record_hash"],
        ),
        kind=Kind(data["kind"]),
        level=Level(data["level"]),
        observed_at=data["observed_at"],
        location=data.get("location", ""),
    )


def _read_vector(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_comparison_vector_inventory_is_exactly_what_is_on_disk():
    """Every named vector present, and no unclassified vector present.

    Both directions. A missing fixture fails NAMING ITSELF, so a deleted vector
    cannot go unnoticed while the family still has siblings; and a vector
    belonging to no family fails too, so a new claim cannot be added without
    being filed under the family it belongs to.
    """
    on_disk = {path.stem for path in _load_vectors(COMPARISON_VECTORS_DIR)}
    expected = frozenset().union(*VECTOR_INVENTORY.values())

    assert on_disk == expected, (
        f"missing: {sorted(expected - on_disk)}; "
        f"unclassified: {sorted(on_disk - expected)}"
    )
    for family, members in VECTOR_INVENTORY.items():
        assert members, f"the {family!r} family names no vectors"
        for stem in members:
            assert stem.startswith(family), (
                f"{stem!r} is filed under {family!r} but is not named for it"
            )


def test_the_outcome_slot_holds_only_the_seven_ratified_strings():
    """Seven rows, and the vectors may mint no eighth.

    Two directions, both enumerable rather than reviewed. An implementation
    that grew a new outcome would ship a state the vectors never pin, and a
    vector naming a string outside the set would ask conforming
    implementations for a value §07 never ratified.
    """
    assert {outcome.value for outcome in Outcome} == {
        "first-contact",
        "unchanged",
        "advanced",
        "rollback",
        "same-height-fork",
        "rewrite",
        "lineage-replaced",
    }
    permitted = {outcome.value for outcome in Outcome} | {None}
    for path in _load_vectors(COMPARISON_VECTORS_DIR):
        outcome = _read_vector(path)["expected"]["outcome"]
        assert outcome in permitted, f"{path.stem} names {outcome!r}"


def test_every_ratified_outcome_is_exercised_by_some_vector():
    """Coverage of the seven as a property, not as a promise in a report.

    The area exists to pin the state machine, so a row no vector reaches is a
    row this family does not actually test. Enumerated here so that adding a
    row without a vector fails rather than passing quietly.
    """
    reached = {
        _read_vector(path)["expected"]["outcome"]
        for path in _load_vectors(COMPARISON_VECTORS_DIR)
    }
    missing = {outcome.value for outcome in Outcome} - reached
    assert not missing, f"no vector reaches: {sorted(missing)}"


def test_every_cell_of_the_bound_is_exercised_by_some_vector():
    """Below, equal, AND above. The third cell is the one a two-valued reading loses.

    ``sound_answer`` has three cells and two of them answer ``null``, so a
    family that exercised only *those* two would go green against an
    implementation that is sound below the bound, declines at it, and answers
    ``advanced`` above it — passing every vector while violating the half of
    the ruling that says nothing bounds the accepted head from above.

    A per-vector assertion cannot see this: each vector is individually
    correct, and the hole is in which vectors EXIST. So coverage of the cells
    is enumerated here, the same way the seven outcomes are, and deleting the
    above-the-bound fixture reopens the hole by failing this test rather than
    by going quietly green.

    **This test asks only whether a cell is OCCUPIED, never whether its
    occupant does any work**, and the two questions fail differently on
    purpose. An empty cell is a gap in the enumeration and is named here. An
    occupant that fills the cell without discriminating anything —
    above-the-bound with no descent evidence — is a gap in the VECTOR, so it
    is named in ``test_conformance_comparison`` against the vector's own id,
    where the failure can say which fixture is hollow and why. Folding the
    second question into this one would report "unexercised bound cells:
    ['above']" about a cell that is not empty, which is a true alarm with a
    false reason.
    """
    cells: set[str] = set()
    for path in _load_vectors(COMPARISON_VECTORS_DIR):
        vector = _read_vector(path)
        expected = vector["expected"]
        if expected.get("read") != "bounded":
            continue
        bound, presented = expected["known"], vector["input"]["presented"]
        if presented["lineage"] != bound["lineage"]:
            continue
        if presented["ordinal"] < bound["ordinal"]:
            cells.add("below")
        elif presented["ordinal"] == bound["ordinal"]:
            cells.add("equal")
        else:
            cells.add("above")

    assert cells == {"below", "equal", "above"}, (
        f"unexercised bound cells: {sorted({'below', 'equal', 'above'} - cells)}"
    )


def test_the_runner_stays_on_the_pure_surface():
    """No vector test may reach a real state root, and not by convention.

    The pure trio resolves no path, so a runner built on it cannot touch
    ``$XDG_STATE_HOME`` whatever the environment holds. Checked against this
    module's actual namespace rather than its source, so the assertion cannot
    be satisfied by a name that merely looks absent — and the impure surface is
    enumerated so that importing one later fails a test instead of quietly
    putting fixture journals in an operator's own memory.
    """
    reachable = set(globals())
    for impure in ("read_journal", "append_entry", "state_root", "journal_path"):
        assert impure not in reachable, f"the runner imports {impure!r}"


@pytest.mark.parametrize(
    "vector_path", _load_vectors(COMPARISON_VECTORS_DIR), ids=lambda p: p.stem
)
def test_conformance_comparison(vector_path: Path) -> None:
    vector = _read_vector(vector_path)

    assert "name" in vector, f"Vector {vector_path} missing 'name'"
    assert "description" in vector, f"Vector {vector_path} missing 'description'"
    assert "input" in vector, f"Vector {vector_path} missing 'input'"
    assert "expected" in vector, f"Vector {vector_path} missing 'expected'"
    assert vector["name"] == vector_path.stem, "vector name must match its file stem"

    presented = _head(vector["input"]["presented"])
    assert presented is not None, "every vector presents a head"
    at_known = _head(vector["input"]["at_known"])
    expected = vector["expected"]

    form = vector["input"]["form"]
    if form == "heads":
        outcome = compare(_entry(vector["input"]["known"]), presented, at_known)
        assert outcome.value == expected["outcome"]
        return

    # An unknown form must fail loudly rather than fall through to green.
    assert form == "journal", f"{vector_path.stem} names form {form!r}"

    lines = [line + "\n" for line in vector["input"]["journal"]]
    state = expected["read"]

    if state in READ_REFUSALS:
        with pytest.raises(READ_REFUSALS[state]):
            parse_journal_lines(lines)
        assert expected["outcome"] is None, "a refused read produces no outcome"
        return

    read = parse_journal_lines(lines)
    # KeyError on an unrecognized state, deliberately.
    assert isinstance(read.known, KNOWN_STATES[state]), (
        f"expected read state {state!r}, got {type(read.known).__name__}"
    )
    assert len(read.entries) == expected["entries"]
    assert len(read.epoch) == expected["epoch"]
    assert len(read.skipped) == expected["skipped"]

    # Each case is named separately BY DESIGN. There is no uniform accessor
    # that reaches a head across the three states — the weakened ones carry no
    # ``entry`` attribute at all — and writing one here would rebuild the
    # shortcut the type split exists to make unobtainable.
    if state == "established":
        assert read.known.entry.head == _head(expected["known"])
    elif state == "bounded":
        assert read.known.at_least.head == _head(expected["known"])
    else:
        assert expected["known"] is None

    try:
        known = read.established_head()
    except IndeterminateComparison:
        assert expected["outcome"] is None, (
            "the read declined, but the vector states an outcome"
        )
    else:
        assert compare(known, presented, at_known).value == expected["outcome"]

    assert ("sound_answer" in expected) == (state == "bounded"), (
        "only a bound carries a sound answer"
    )
    if state == "bounded":
        bound = read.known.at_least.head
        below = (
            presented.lineage == bound.lineage
            and presented.ordinal < bound.ordinal
        )
        assert expected["sound_answer"] in SOUND_ANSWERS
        assert expected["sound_answer"] == ("rollback" if below else None)

        if presented.lineage == bound.lineage and presented.ordinal > bound.ordinal:
            # An above-the-bound vector must carry descent evidence naming the
            # BOUND'S OWN coordinate and hash — equality, not merely non-null.
            # The vector's whole force is a counterfactual: even with descent
            # fully established from the bound, the proceed answer stays
            # unobtainable. Weaken at_known and the vector stops discriminating,
            # because a declining implementation could be right for the wrong
            # reason — with a null at_known the classifier answers `rewrite` for
            # want of evidence, and with a non-matching one it answers `rewrite`
            # too. Both are already pinned by the `comparison-classify-rewrite-`
            # vectors, so a hollow above-the-bound vector is a duplicate of a
            # classify row wearing an incomplete-read costume: it occupies the
            # cell without ever making `advanced` the answer a bound-ignoring
            # implementation would reach for.
            assert at_known == bound, (
                f"{vector_path.stem} presents a head above the bound but "
                f"supplies at_known={vector['input']['at_known']!r}. An "
                "above-the-bound vector must name the bound's own coordinate "
                "and hash, or it cannot tell 'a bound cannot answer above "
                "itself' from 'there was no descent evidence anyway' — an "
                "implementation declining for the second reason would pass it "
                "while still answering `advanced` wherever descent IS proven."
            )

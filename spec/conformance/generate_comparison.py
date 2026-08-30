"""Generator for comparison conformance vectors.

Builds golden vectors pinning the head-comparison state machine — slice 3 of the
arrival break, ``witness-protocol.html`` §07 as amended by the slice-3 rulings.
The question the area answers is the one no backend can answer about itself: *is
the log in front of me the same log this machine accepted yesterday?*

**Two vector forms, and the split is the area's design point.**

- ``form: "heads"`` hands a ``(known, presented, at_known)`` triple straight to
  the pure classifier. These pin the seven §07 rows with NO journal encoding,
  because §B.3's journal is a local cache grammar rather than wire — it is
  deliberately not the record codec, it versions independently, and no other
  implementation is obliged to have one. Routing every row through a journal
  fixture would pin this repo's cache format onto an implementation that owes
  only the state machine.
- ``form: "journal"`` hands raw lines to the pure reader and then attempts the
  comparison. Every read rule lives here and NONE of them is reachable from the
  classifier: trust-epoch scoping, the maximum-ordinal rule, equivocation, the
  incomplete-read lower bound, the header's three-way classification.

Five families, each answering a question the others cannot:

- ``comparison-classify-*``: the seven rows, in isolation, plus the guard-order
  claim that a foreign lineage is judged before any ordinal arithmetic.
- ``comparison-epoch-*``: a trust-reset opens a new epoch, RESET-INCLUSIVE, and
  the epoch scopes the equivocation check too.
- ``comparison-journal-*``: the maximum-ordinal read rule, equivocation and its
  agreement control, and the two journals that are honestly first contact.
- ``comparison-incomplete-*``: an incomplete read yields a LOWER BOUND — sound
  below itself, unable to answer either proceed row — and the third state where
  content was claimed and nothing at all could be read.
- ``comparison-header-*``: the three-way classification, which never absorbs a
  line and never refuses the file.

Every vector is deterministic: one fixed lineage, fixed observation times, and
record hashes derived from a fixed tag. Nothing here reads a clock.

**Trust resets are position-bound, so fixture ORDER is now part of the frozen
output.** A reset records the physical line its predecessor occupies, so
inserting, removing or reordering a line in any fixture that contains a reset
changes that reset's ``follows`` — by design, since a binding that survived
being moved would not be a position claim. Regenerating after such an edit is
correct and expected; a stale hand-edited vector is not.

Well-formed journals are built through the real ``append_entry`` so the vectors
pin the writer's actual bytes, under a TEMPORARY ``XDG_STATE_HOME`` that is
asserted before the first append — this generator must never touch a real state
root. Damage, ambiguity and foreign-build lines are spliced in afterwards, since
they are by definition what the writer would not produce.

Run once to generate/regenerate frozen vector files:
    uv run --package engine python spec/conformance/generate_comparison.py
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from engine.arrival_contract import Head
from engine.arrival_head_attestation import (
    HeadAttestation,
    HeadLowerBound,
    HeadUnreadable,
    IndeterminateComparison,
    JournalEquivocation,
    Kind,
    Level,
    append_entry,
    compare,
    entry_identity,
    journal_path,
    last_entry,
    parse_journal_lines,
    state_root,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPARISON_DIR = REPO_ROOT / "spec" / "conformance" / "vectors" / "comparison"

# One fixed lineage across the area, so a reader comparing two vectors is
# comparing histories and not identifiers. The second exists only to be a
# DIFFERENT one.
LINEAGE = "01M3COMPARISONVECTORLINEAGE"
OTHER_LINEAGE = "01M3COMPARISONREPLACEMENT"

# Fixed observation times. Witness metadata, never ledger order — so they are
# constants rather than a clock, and nothing in the area depends on their order.
OBSERVED_AT = 1788000000.0
LOCATION = "/vectors/comparison/project.arrival"

# The serialized type marker, restated rather than imported from the module's
# private constant: a vector generator that reached into a private name would
# make the frozen artifacts a function of an implementation detail.
OBSERVATION_TYPE = "arrival-head-observation"


def rh(tag: str) -> str:
    """A deterministic stand-in record hash: 64 hex, stable across runs.

    The journal stores heads it was handed and validates no hash, so these need
    to be well-shaped rather than real. Derived from a tag so that two vectors
    naming the same tag mean the same head and a reader can see it.
    """
    return hashlib.sha256(f"comparison-vector/{tag}".encode()).hexdigest()


def head(ordinal: int, tag: str | None = None, lineage: str = LINEAGE) -> Head:
    return Head(
        lineage=lineage, ordinal=ordinal, record_hash=rh(tag or f"ord-{ordinal}")
    )


def entry(
    ordinal: int,
    *,
    kind: Kind = Kind.ADVANCE,
    level: Level = Level.COMMIT,
    tag: str | None = None,
    observed_at: float | None = None,
) -> HeadAttestation:
    return HeadAttestation(
        head=head(ordinal, tag),
        kind=kind,
        level=level,
        observed_at=OBSERVED_AT + ordinal if observed_at is None else observed_at,
        location=LOCATION,
    )


def bootstrap() -> HeadAttestation:
    """The first entry, at Level.MINT — this process minted the genesis."""
    return entry(0, kind=Kind.BOOTSTRAP, level=Level.MINT)


def reset(ordinal: int) -> HeadAttestation:
    """An operator ceremony accepting a restore back to ``ordinal``.

    ``Level.FULL`` because an operator who ran the ceremony verified from
    genesis. Not load-bearing for any read rule: the epoch scope keys on
    ``Kind.TRUST_RESET`` alone.

    **``follows`` is left unset here and bound at WRITE time** by
    :func:`lines_for`, because the claim it carries — the physical line its
    predecessor occupies — is a fact about the journal being built and not
    about the ceremony. A reset constructed with a stale binding is exactly
    what the read rejects, so the generator cannot guess it in advance any
    more than an operator can.
    """
    return entry(ordinal, kind=Kind.TRUST_RESET, level=Level.FULL)


def head_json(value: Head | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "lineage": value.lineage,
        "ordinal": value.ordinal,
        "record_hash": value.record_hash,
    }


def entry_json(value: HeadAttestation | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "kind": value.kind.value,
        "level": value.level.value,
        "lineage": value.head.lineage,
        "ordinal": value.head.ordinal,
        "record_hash": value.head.record_hash,
        "observed_at": value.observed_at,
        "location": value.location,
    }


# ---------------------------------------------------------------------------
# Line transforms — what a correct writer would never produce
# ---------------------------------------------------------------------------


def drop_header(lines: list[str]) -> list[str]:
    """Remove the header, leaving readable entries with nothing describing them."""
    return [line for line in lines if '"kind"' in line]


def keep_header_only(lines: list[str]) -> list[str]:
    return [line for line in lines if '"kind"' not in line]


def torn(ordinal: int) -> Callable[[list[str]], list[str]]:
    """Truncate the line holding ``ordinal`` mid-JSON, as a crash would."""

    def apply(lines: list[str]) -> list[str]:
        return [
            line[: len(line) // 2] if f'"ordinal":{ordinal},' in line else line
            for line in lines
        ]

    return apply


def replace_at(ordinal: int, raw: str) -> Callable[[list[str]], list[str]]:
    """Swap the line holding ``ordinal`` for a literal one."""

    def apply(lines: list[str]) -> list[str]:
        return [
            raw if f'"ordinal":{ordinal},' in line else line for line in lines
        ]

    return apply


def replace_header(raw: str) -> Callable[[list[str]], list[str]]:
    def apply(lines: list[str]) -> list[str]:
        return [raw if '"kind"' not in line else line for line in lines]

    return apply


def add_unknown_fields(ordinal: int) -> Callable[[list[str]], list[str]]:
    """Give one v1 entry fields this build has never heard of."""

    def apply(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            if f'"ordinal":{ordinal},' in line:
                decoded = json.loads(line)
                decoded["issued_by"] = "a-later-build"
                decoded["corroboration"] = {"facts": 41, "ticks": 7}
                line = json.dumps(decoded, separators=(",", ":"), sort_keys=True)
            out.append(line)
        return out

    return apply


#: A header written by a build after this one: kindless, bearing the type
#: marker, carrying fields this build does not know. Still a header.
LATER_BUILD_HEADER = json.dumps(
    {
        "v": 2,
        "type": OBSERVATION_TYPE,
        "protocol": 2,
        "wire": 2,
        "issuer": "a-later-build",
    },
    separators=(",", ":"),
    sort_keys=True,
)

#: A line carrying BOTH the journal type marker and an entry kind. Neither
#: repair works: absorbing it as a header loses an entry silently, and refusing
#: it refuses the file over version skew.
AMBIGUOUS_LINE = json.dumps(
    {
        "v": 1,
        "type": OBSERVATION_TYPE,
        "kind": "advance",
        "level": "commit",
        "lineage": LINEAGE,
        "ordinal": 92,
        "record_hash": rh("ord-92"),
        "observed_at": OBSERVED_AT + 92,
    },
    separators=(",", ":"),
    sort_keys=True,
)


def later_build_entry(ordinal: int, tag: str) -> str:
    """An entry at journal grammar v2: readable JSON, unusable by this build."""
    return json.dumps(
        {
            "v": 2,
            "kind": "advance",
            "level": "commit",
            "lineage": LINEAGE,
            "ordinal": ordinal,
            "record_hash": rh(tag),
            "observed_at": OBSERVED_AT + ordinal,
            "custody": {"chain": "a-later-build"},
        },
        separators=(",", ":"),
        sort_keys=True,
    )


#: A journal written ENTIRELY by a later build: its own header, its own
#: entries. No attacker, only version skew.
PURE_SKEW_JOURNAL = (
    LATER_BUILD_HEADER,
    later_build_entry(4216, "skew-4216"),
    later_build_entry(4217, "skew-4217"),
)


# ---------------------------------------------------------------------------
# The cases
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HeadsCase:
    """A triple handed straight to the classifier. No journal involved."""

    name: str
    description: str
    known: HeadAttestation | None
    presented: Head
    at_known: Head | None = None


@dataclass(frozen=True)
class JournalCase:
    """Raw journal lines, then the comparison that follows from reading them."""

    name: str
    description: str
    presented: Head
    # Written through the real appender, in this order.
    entries: tuple[HeadAttestation, ...] = ()
    # Applied to the written lines. What a correct writer would never produce.
    transform: Callable[[list[str]], list[str]] | None = None
    # Used verbatim INSTEAD of writing anything, for foreign-build fixtures.
    raw_lines: tuple[str, ...] | None = None
    at_known: Head | None = None


HEADS_CASES: tuple[HeadsCase, ...] = (
    HeadsCase(
        name="comparison-classify-first-contact",
        description=(
            "Nothing is remembered, so there is nothing to compare against. §07 "
            "lists first contact separately from the five comparisons, and it is "
            "trust on first use — labeled, never silent. Refusing instead would "
            "make a fresh clone unable to read anything."
        ),
        known=None,
        presented=head(0, "genesis"),
    ),
    HeadsCase(
        name="comparison-classify-unchanged",
        description=(
            "The presented head equals the remembered one in all three fields. "
            "The dominant case, and it is answered without consulting at_known: "
            "there is nothing to discriminate, so asking would make the common "
            "path pay for evidence it does not need."
        ),
        known=entry(7),
        presented=head(7),
    ),
    HeadsCase(
        name="comparison-classify-advanced",
        description=(
            "A higher ordinal in the same lineage, AND the ledger vouches for the "
            "remembered head at its own coordinate. Both halves are required: "
            "at_known is what turns 'the chain reaches the presented head' into "
            "'the chain still contains what we accepted'."
        ),
        known=entry(7),
        presented=head(9),
        at_known=head(7),
    ),
    HeadsCase(
        name="comparison-classify-rollback",
        description=(
            "A lower ordinal in the same lineage. Refuse: the response is to "
            "locate a replica at or above the witnessed head, never to move the "
            "witness backward to match the store. at_known is supplied here and "
            "is deliberately not consulted — the descending branch needs no "
            "evidence beyond the height."
        ),
        known=entry(7),
        presented=head(4),
        at_known=head(7),
    ),
    HeadsCase(
        name="comparison-classify-same-height-fork",
        description=(
            "The same ordinal in the same lineage with a different record hash: "
            "two histories disagree about what happened at that height. Refuse "
            "and freeze both branches — never pick the taller one, since height "
            "is not evidence of continuity."
        ),
        known=entry(7),
        presented=head(7, "forked"),
    ),
    HeadsCase(
        name="comparison-classify-rewrite-at-the-known-ordinal",
        description=(
            "The head advanced, but the record now sitting at the REMEMBERED "
            "ordinal is not the one we accepted. The chain in front of us may "
            "verify perfectly and still be a different history; a walk that only "
            "checks it reached the presented head answers nothing about "
            "continuity with what came before."
        ),
        known=entry(7),
        presented=head(9),
        at_known=head(7, "rewritten"),
    ),
    HeadsCase(
        name="comparison-classify-rewrite-when-the-ledger-vouches-for-nothing",
        description=(
            "The second way the advance branch fails: descent was never "
            "established at all, so at_known is null. Absence of evidence is not "
            "evidence of descent — an unproven advance is a rewrite, not an "
            "advance with a caveat."
        ),
        known=entry(7),
        presented=head(9),
        at_known=None,
    ),
    HeadsCase(
        name="comparison-classify-lineage-replaced",
        description=(
            "A different lineage where a known one was expected: the store was "
            "replaced wholesale rather than moved. Where the expected lineage is "
            "declared a backend's own authority refusal fires first, but the "
            "classifier owns the row because a caller that reached the comparison "
            "without a declared lineage still needs it."
        ),
        known=entry(7),
        presented=head(9, lineage=OTHER_LINEAGE),
    ),
    HeadsCase(
        name="comparison-classify-lineage-replaced-outranks-a-lower-ordinal",
        description=(
            "GUARD ORDER, stated as its own claim. A foreign lineage at a LOWER "
            "ordinal is a replacement, never a rollback: heights across two "
            "lineages are unrelated number lines. Answering rollback here would "
            "send an operator hunting for a backup of a lineage that was never "
            "involved."
        ),
        known=entry(7),
        presented=head(4, lineage=OTHER_LINEAGE),
    ),
)


JOURNAL_CASES: tuple[JournalCase, ...] = (
    # --- family: the trust epoch -------------------------------------------
    JournalCase(
        name="comparison-epoch-ends-at-the-reset-entry-is-unchanged",
        description=(
            "The trust epoch is RESET-INCLUSIVE: the reset entry is the first "
            "entry of the epoch it opens, not excluded from it. A journal whose "
            "last entry is the reset therefore compares against the RESET head — "
            "unchanged — and not against the abandoned maximum above it. Read the "
            "epoch as 'the entries after the reset' and this journal has an empty "
            "epoch, nothing remembered, and first contact: silent re-acceptance "
            "on the most ordinary shape there is, an operator resetting and then "
            "opening. The abandoned entry stays in the journal as EVIDENCE, which "
            "is the whole point of recording the gap."
        ),
        entries=(bootstrap(), entry(100), reset(90)),
        presented=head(90),
    ),
    JournalCase(
        name="comparison-epoch-below-the-reset-head-is-rollback",
        description=(
            "The other half of the same claim, and the one that proves the "
            "comparison is against the reset head rather than merely against "
            "SOMETHING. A store presenting a head below the accepted restore "
            "point still refuses. A ceremony that re-established trust at 90 did "
            "not license everything beneath it."
        ),
        entries=(bootstrap(), entry(100), reset(90)),
        presented=head(89),
    ),
    JournalCase(
        name="comparison-epoch-scopes-the-equivocation-check-too",
        description=(
            "Epoch scoping governs all three surfaces, not just which entry is "
            "the remembered head. This journal holds an equivocating pair ABOVE "
            "the current epoch — two different records claiming ordinal 200 — and "
            "the read completes cleanly, because those entries were abandoned by "
            "the reset and are retained as evidence rather than as claims. "
            "Unscoped, the ceremony could never take effect: the journal would "
            "refuse forever over a conflict the operator already resolved."
        ),
        entries=(
            bootstrap(),
            entry(200, tag="branch-a"),
            entry(200, tag="branch-b"),
            reset(90),
            entry(91),
        ),
        presented=head(91),
    ),
    # --- family: the read rules --------------------------------------------
    JournalCase(
        name="comparison-journal-the-known-head-is-the-maximum-ordinal",
        description=(
            "The remembered head is the epoch's MAXIMUM-ordinal entry, not the "
            "last line. Two writers append concurrently — the arrival lock "
            "serializes their appends, not their journal writes — so lines land "
            "out of order: A commits 5, B commits 6 and journals it, A journals 5 "
            "last. Here the store presents the head recorded at ordinal 5, which "
            "is a genuine restore from 6. Last-line semantics would read the "
            "remembered head as 5 and call this unchanged, which is exactly the "
            "silent re-acceptance the rule exists to close."
        ),
        entries=(bootstrap(), entry(6), entry(5)),
        presented=head(5),
    ),
    JournalCase(
        name="comparison-journal-equivocation-refuses-the-read",
        description=(
            "Two entries at the epoch's maximum ordinal with DIFFERENT record "
            "hashes. The journal has recorded two incompatible histories and it "
            "is not the journal's place to choose between them, so the read "
            "refuses before any comparison — there is no outcome, because the "
            "question of which head was accepted has no answer here."
        ),
        entries=(bootstrap(), entry(6, tag="branch-a"), entry(6, tag="branch-b")),
        presented=head(6, "branch-a"),
    ),
    JournalCase(
        name="comparison-journal-agreeing-entries-at-the-maximum-are-not-equivocation",
        description=(
            "The negative control for equivocation. Two entries at the maximum "
            "ordinal carrying the SAME record hash are a duplicate observation, "
            "not a conflict — a writer journaling a head twice records nothing "
            "new and contradicts nothing. An equivocation refusal that fired here "
            "would have stopped meaning equivocation. The two lines differ in "
            "``observed_at``, and that is now load-bearing rather than "
            "incidental: agreement and BYTE-IDENTITY are different claims, and "
            "since the dedup rule takes byte-identical lines before the "
            "equivocation check ever sees them, a byte-identical fixture would "
            "no longer reach the control it was written to be. Two observations "
            "of one head made at different moments is what 'agreeing entries' "
            "means once literal re-assertions are removed from the file."
        ),
        entries=(
            bootstrap(),
            entry(6, observed_at=OBSERVED_AT + 6),
            entry(6, observed_at=OBSERVED_AT + 600),
        ),
        presented=head(6),
    ),
    JournalCase(
        name="comparison-journal-a-byte-identical-line-is-a-re-assertion",
        description=(
            "The dedup rule, and the claim it makes is about ARITHMETIC rather "
            "than about damage. A line whose exact bytes duplicate an earlier "
            "line re-asserts an observation the journal already holds; it is not "
            "a fresh one, and it is skipped with a record before the epoch and "
            "the remembered head are computed. Without this, a replayed "
            "historical advance counts as a current observation, the "
            "maximum-ordinal rule takes it as the remembered head, and a store "
            "restored from a pre-reset backup presents that head exactly — "
            "answering UNCHANGED for ceremonially abandoned state. Type-agnostic "
            "and order-agnostic, but NOT applied to headers: two writers racing "
            "to create one journal each write a header, and that duplicate is "
            "the tolerated create-race artifact rather than a replay. Note what "
            "the skip costs here — a non-empty skip set is what weakens a read, "
            "so this journal yields a BOUND even though the duplicated line "
            "carried no information that was lost. That conservative direction "
            "is the ruled behavior as of this vector's writing, and it is the "
            "one place a reader knows exactly what the skipped line said; "
            "whether an information-free skip should weaken the read is an open "
            "question routed to the arbiter, and this vector is what would be "
            "regenerated if it is ruled the other way."
        ),
        entries=(bootstrap(), entry(6), entry(6)),
        presented=head(6),
    ),
    JournalCase(
        name="comparison-journal-an-empty-journal-is-first-contact",
        description=(
            "No lines at all. An empty journal says nothing was ever accepted "
            "here, and trust on first use is the honest answer to it. This is the "
            "boundary the third state sits against: content claimed and "
            "unreadable is NOT this."
        ),
        entries=(),
        presented=head(0, "genesis"),
    ),
    JournalCase(
        name="comparison-journal-a-header-only-journal-is-first-contact",
        description=(
            "A header and no entries. Still first contact: the header describes "
            "the file's grammar and claims no head, so nothing has been accepted "
            "here and nothing has been lost. First contact must stay reachable "
            "wherever it is honest, or the third state would have swallowed it."
        ),
        entries=(bootstrap(),),
        transform=keep_header_only,
        presented=head(0, "genesis"),
    ),
    JournalCase(
        name="comparison-journal-unknown-fields-on-a-v1-entry-are-read",
        description=(
            "The second negative control. An entry at THIS journal grammar "
            "version carrying fields this build has never heard of is read "
            "normally — the journal is append-only and never rewritten, so "
            "unknown fields are preserved on disk by construction and ignored on "
            "read. What makes an entry unusable is the grammar version, not "
            "unfamiliar content; a reader that skipped on unfamiliar fields would "
            "weaken its own claim over nothing."
        ),
        entries=(bootstrap(), entry(6)),
        transform=add_unknown_fields(6),
        presented=head(6),
    ),
    # --- family: the incomplete read ---------------------------------------
    JournalCase(
        name="comparison-incomplete-a-torn-line-yields-a-lower-bound",
        description=(
            "The fixture that refuted 'a mid-file skip is strictly safer than a "
            "torn tail'. One epoch in file order [reset 90, 92, 91], true "
            "remembered head 92; the line holding 92 is torn by a crash, and a "
            "later well-formed entry survives after it. Skipping quietly would "
            "lower the remembered head to 91 and call a genuine restore from 92 "
            "UNCHANGED. So the loss is carried in the read's own type instead: "
            "the head is known only to be AT LEAST 91, and a presented head EQUAL "
            "to the bound cannot be called unchanged, because it may be a "
            "rollback from the very entry the read missed. Note what is NOT done "
            "— the file is not refused. Refusing would make an ordinary crash a "
            "permanent incident, and it claims a protection this location cannot "
            "deliver anyway, since anyone able to corrupt a line can delete the "
            "journal instead and be met with trust on first use."
        ),
        entries=(bootstrap(), reset(90), entry(92), entry(91)),
        transform=torn(92),
        presented=head(91),
    ),
    JournalCase(
        name="comparison-incomplete-a-bound-still-refuses-below-itself",
        description=(
            "What a bound CAN answer, which is the half a decline-only reading "
            "would lose. The accepted head is at least 91, so a store presenting "
            "89 is certainly below it and that is a rollback on any reading. The "
            "bound is sound downward and unobtainable in both proceed directions: "
            "nothing bounds the accepted head from ABOVE either, so a head above "
            "the bound is not an advance — a lost entry may have sat at 200."
        ),
        entries=(bootstrap(), reset(90), entry(92), entry(91)),
        transform=torn(92),
        presented=head(89),
    ),
    JournalCase(
        name="comparison-incomplete-a-bound-cannot-answer-above-itself",
        description=(
            "The third cell of the bound, and the one a two-celled reading "
            "loses. Below the bound is a sound rollback and at the bound "
            "declines — but a head ABOVE the bound is not an advance either, "
            "because NOTHING BOUNDS THE ACCEPTED HEAD FROM ABOVE. Whatever the "
            "read missed carries no information about the ordinal it held. This "
            "fixture exhibits it rather than merely asserting it: the entry the "
            "crash tore held ordinal 200, so the head this machine actually "
            "accepted was 200, and a store presenting 95 is a ROLLBACK of "
            "105 ordinals. An implementation answering 'advanced' because 95 "
            "exceeds the surviving bound of 91 would wave through exactly the "
            "loss the journal exists to catch. Note that at_known is supplied "
            "and valid — descent from 91 to 95 really is established — which is "
            "the point: descent verified from the bound says nothing about an "
            "entry that was never on the walk. Both proceed answers are "
            "unobtainable against a bound; only the refusal below it survives."
        ),
        entries=(bootstrap(), reset(90), entry(200), entry(91)),
        transform=torn(200),
        presented=head(95),
        at_known=head(91),
    ),
    JournalCase(
        name="comparison-incomplete-a-headerless-journal-yields-a-bound",
        description=(
            "Readable entries with no header. This once refused the whole file; "
            "it yields a BOUND instead, with the absence reported without a line "
            "number because an absence does not have one. The entries are "
            "self-describing evidence that heads were accepted, and what was lost "
            "— the protocol and wire versions those record hashes derive under — "
            "is exactly the kind of loss a lower bound is for. Refusing here would "
            "be a verdict where a bound will do."
        ),
        entries=(bootstrap(), entry(6)),
        transform=drop_header,
        presented=head(6),
    ),
    JournalCase(
        name="comparison-incomplete-nothing-readable-declines-every-comparison",
        description=(
            "The third state, and it is not the absence of one. This journal was "
            "written entirely by a later build — its own header, its own entries "
            "— so no attacker is involved, only version skew. Content was claimed "
            "and none of it could be read, which says heads WERE accepted here and "
            "their ordinals are precisely what was lost. There is no bound, so "
            "unlike an incomplete read this cannot even answer rollback: every "
            "comparison declines. Collapsing this into first contact would grant "
            "trust on first use PRECISELY BECAUSE the journal became unreadable."
        ),
        raw_lines=PURE_SKEW_JOURNAL,
        presented=head(4217, "skew-4217"),
    ),
    JournalCase(
        name="comparison-incomplete-a-re-mint-against-lost-content-is-not-first-contact",
        description=(
            "The consequence stated as its own vector, because it is the one an "
            "operator would meet. A fresh genesis at ordinal 0 arrives at a "
            "location whose journal remembers ordinal 4217 in unreadable form. "
            "That is a replacement wearing the old name — the case the store-lost "
            "refusal exists for — and reaching it through the "
            "forward-compatibility path would be a downgrade attack in the "
            "adversarial reading and silent re-acceptance in the ordinary one. It "
            "declines."
        ),
        raw_lines=PURE_SKEW_JOURNAL,
        presented=head(0, "re-mint"),
    ),
    # --- family: the three-way header classification ------------------------
    JournalCase(
        name="comparison-header-a-kindless-object-is-not-absorbed",
        description=(
            "A bare kindless object where an entry should be. Treating any "
            "kindless dict as a header absorbed this silently, recording NO skip "
            "— and on an out-of-order journal that quietly dropped the line "
            "holding the epoch maximum, turning a rollback into unchanged. It is "
            "an entry this build cannot name, so it is skipped and reported, and "
            "the read weakens to a bound that refuses to answer unchanged."
        ),
        entries=(bootstrap(), entry(92), entry(91)),
        transform=replace_at(92, "{}"),
        presented=head(91),
    ),
    JournalCase(
        name="comparison-header-both-markers-together-are-unclassifiable",
        description=(
            "The middle row of the three-way rule, and the whole reason the rule "
            "is three-way rather than a predicate. A line carrying BOTH the "
            "journal type marker and an entry kind is not classified at all: "
            "never absorbed as a header (which would silently lose an entry), "
            "never a reason to refuse the file (which would be an uncontracted "
            "version-skew refusal of everything). It is skipped and reported "
            "naming the ambiguity — a location claim about this build's ability to "
            "read the line, NOT a verdict about what the line is, which is exactly "
            "what this build cannot know. Both obvious repairs fail in opposite "
            "directions; admitting a third verdict is what makes the reader stop "
            "having to choose between two wrong certainties."
        ),
        entries=(bootstrap(), entry(92), entry(91)),
        transform=replace_at(92, AMBIGUOUS_LINE),
        presented=head(91),
    ),
    JournalCase(
        name="comparison-header-a-later-builds-header-is-still-a-header",
        description=(
            "The complement, and the case that keeps a shared journal from "
            "bricking an older build. A header from a later grammar — kindless, "
            "bearing the type marker, carrying fields this build does not know — "
            "is recognized as the header it is. Nothing is skipped, the read is "
            "complete, and the comparison answers in full. Requiring the type "
            "marker AND the absence of a kind would leave a later header "
            "unrecognized, its entries headerless, and the file weakened over "
            "ordinary version skew."
        ),
        entries=(bootstrap(), entry(6)),
        transform=replace_header(LATER_BUILD_HEADER),
        presented=head(6),
    ),
)


# ---------------------------------------------------------------------------
# Deriving the expectations by running the real module
# ---------------------------------------------------------------------------


def lines_for(case: JournalCase) -> list[str]:
    """The journal this case presents, built through the real writer.

    Well-formed entries go through ``append_entry`` so the vectors pin the
    bytes the writer actually emits — including the header it writes on create.
    A transform then splices in what a correct writer would never produce.

    **A trust reset is bound to its predecessor here**, from the journal as it
    stands at the moment of the append: the physical line the previous entry
    occupies and that entry's identity. This is the same computation
    ``arrival_head_seam.trust_reset`` performs, spelled with the two primitives
    the attestation module exports for it rather than by importing the seam —
    the seam canonicalizes its ``location`` through ``Path.resolve()``, which
    is a function of the machine the generator runs on and would make frozen
    vectors non-reproducible.
    """
    if case.raw_lines is not None:
        return list(case.raw_lines)
    path = journal_path(LINEAGE)
    path.unlink(missing_ok=True)
    for item in case.entries:
        if item.kind is Kind.TRUST_RESET:
            previous = last_entry(LINEAGE)
            item = replace(
                item,
                follows=(0, "")
                if previous is None
                else (previous[0], entry_identity(previous[1])),
            )
        append_entry(item)
    lines = (
        path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    )
    return case.transform(lines) if case.transform else lines


def journal_expectation(case: JournalCase, lines: list[str]) -> dict[str, Any]:
    """Read, then compare, and state exactly how far each got."""
    try:
        read = parse_journal_lines(line + "\n" for line in lines)
    except JournalEquivocation:
        # The read never reached a head, so there is nothing to count and no
        # outcome to state. Null rather than zero: the read did not find none
        # of these things, it never got far enough to look.
        return {
            "read": "equivocation",
            "known": None,
            "entries": None,
            "epoch": None,
            "skipped": None,
            "outcome": None,
        }

    if isinstance(read.known, HeadLowerBound):
        state, known = "bounded", read.known.at_least.head
    elif isinstance(read.known, HeadUnreadable):
        state, known = "unreadable", None
    elif read.known is None:
        state, known = "none", None
    else:
        state, known = "established", read.known.entry.head

    expected: dict[str, Any] = {
        "read": state,
        "known": head_json(known),
        "entries": len(read.entries),
        "epoch": len(read.epoch),
        "skipped": len(read.skipped),
    }

    try:
        outcome = compare(read.established_head(), case.presented, case.at_known)
    except IndeterminateComparison:
        expected["outcome"] = None
    else:
        expected["outcome"] = outcome.value

    if state == "bounded":
        # The positive half of lower-bound semantics. ROLLBACK-ONLY, as ruled:
        # a presented head below the bound is certainly below the accepted head,
        # and that is the only comparison a bound can make.
        assert known is not None
        expected["sound_answer"] = (
            "rollback"
            if case.presented.lineage == known.lineage
            and case.presented.ordinal < known.ordinal
            else None
        )
    return expected


def write_vector(vector: dict[str, Any], note: str) -> None:
    out_path = COMPARISON_DIR / f"{vector['name']}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(vector, fh, indent=2)
        fh.write("\n")
    print(f"Wrote {out_path.relative_to(REPO_ROOT)} ({note})")


def generate_comparison_vectors() -> None:
    COMPARISON_DIR.mkdir(parents=True, exist_ok=True)

    for case in HEADS_CASES:
        outcome = compare(case.known, case.presented, case.at_known)
        write_vector(
            {
                "name": case.name,
                "description": case.description,
                "input": {
                    "form": "heads",
                    "known": entry_json(case.known),
                    "presented": head_json(case.presented),
                    "at_known": head_json(case.at_known),
                },
                "expected": {"outcome": outcome.value},
            },
            outcome.value,
        )

    with tempfile.TemporaryDirectory() as tmp:
        # NEVER a real state root. Asserted rather than trusted: this generator
        # writes through the real appender, so a stale environment would put
        # fixture journals in the operator's own memory.
        os.environ["XDG_STATE_HOME"] = tmp
        assert state_root() == Path(tmp) / "loops", state_root()
        assert journal_path(LINEAGE).is_relative_to(tmp), journal_path(LINEAGE)

        for case in JOURNAL_CASES:
            lines = lines_for(case)
            expected = journal_expectation(case, lines)
            write_vector(
                {
                    "name": case.name,
                    "description": case.description,
                    "input": {
                        "form": "journal",
                        "journal": lines,
                        "presented": head_json(case.presented),
                        "at_known": head_json(case.at_known),
                    },
                    "expected": expected,
                },
                f"{expected['read']} / {expected['outcome']}",
            )


if __name__ == "__main__":
    generate_comparison_vectors()

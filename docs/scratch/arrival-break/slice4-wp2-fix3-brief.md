# Slice 4 WP2 — fix round 3 (one regression: tick era absence-vs-null)

## Working directory — verify FIRST

    /Users/kaygee/Code/loops-wt/s4-wp2

Prefix EVERY command with `cd /Users/kaygee/Code/loops-wt/s4-wp2 && `. First:

    cd /Users/kaygee/Code/loops-wt/s4-wp2 && pwd && git branch --show-current && git log --oneline -1

Expected: branch `slice4/wp2`, HEAD 5a531574. Otherwise STOP and report. Test env:
`TMPDIR=/Users/kaygee/Code/loops-wt/s4-wp2/.tmp`, pytest `--basetemp=.../.tmp/pt`.

## EXECUTE YOURSELF — DO NOT DELEGATE. One response.

## Scope fence

ONLY `libs/migrate/**`. Nothing else. Never touch `.loops/`, never run `sl`/`loops` emit.

## The fix (gate R3-B1, ruled; the prescription is exact)

Routing the tick arm through `row_object_fault` (correct) introduced a regression: the
tick object handed to it is built from `_tick_columns()`, which is era-aware and returns
only the columns the store HAS. `row_object_fault` faults on field ABSENCE before
consulting nullability, and `TICK_FIELDS` lists all four chain fields — so a ticks table
predating the chain columns is refused, though the frozen grammar licenses those fields as
null (`TICK_NULLABLE = frozenset(("since", *TICK_CHAIN_FIELDS))`). Absence and null are
conflated in the one direction the grammar forbids. Proven a regression: the same era-1
store migrated correctly at 9c1a9372 (tick body with all four chain fields None) and is
refused at 5a531574.

Fix, in `legacy_source.py`'s tick arm: build the object as
`obj = {f: t_dict.get(f) for f in TICK_FIELDS}`, re-adding `signature` only when non-None —
an absent column becomes a null field, which `TICK_NULLABLE` already permits. The facts arm
needs NO equivalent change (`FACT_FIELDS` has no nullable members; `signature` is not in
`FACT_FIELDS`; `_facts_have_signature` handles that column's absence).

Test alongside: an era-1 sqlite fixture whose ticks table LACKS the four chain columns
(and `since`), asserting (a) inventory succeeds with the right tick count, (b) transform
produces a tick body carrying explicit nulls for the chain fields, (c) both surfaces agree.

## Acceptance bar

COMMIT FIRST, then the break/restore proof: revert the object-building line to the
columns-present-only dict → the era-1 test fails with the exact "missing field(s) in tick
row" refusal; restore → green; paste both plus the empty production diff.

Final: `uv run pytest libs/migrate tests/architecture -q` all green (expect 142+);
`git status --short` clean but `.tmp/`.

## Report (stdout, one shot): change, proof evidence, anything else observed, honest gaps.

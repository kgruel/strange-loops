# Slice 4 WP2 — fix round 2 (two narrow blockings from gate round 2)

## Working directory — verify FIRST

    /Users/kaygee/Code/loops-wt/s4-wp2

Prefix EVERY command with `cd /Users/kaygee/Code/loops-wt/s4-wp2 && `. First:

    cd /Users/kaygee/Code/loops-wt/s4-wp2 && pwd && git branch --show-current && git log --oneline -1

Expected: branch `slice4/wp2`, HEAD 9c1a9372. Otherwise STOP and report. Test env:
`TMPDIR=/Users/kaygee/Code/loops-wt/s4-wp2/.tmp`, pytest `--basetemp=.../.tmp/pt`.

## EXECUTE YOURSELF — DO NOT DELEGATE. One response, no questions.

## Scope fence

ONLY `libs/migrate/**`. Nothing else, no cleanup in passing, never touch `.loops/` or run
`sl`/`loops` emit. STOP and report anything needing more.

## The two fixes — both RULED, both contained

**F1 (gate R2-B1) — route the sqlite arm through the one grammar.** `legacy_source.py`'s
sqlite arm hand-validates fields (:410-422, :462-487) and has already diverged:
`row_object_fault` enforces the JCS safe-integer domain; the sqlite arm checks only
`math.isfinite`. Probe that must go from broken to fixed: a sqlite store whose INTEGER `ts`
holds `2**60` → today transform leaks `ArrivalBodyError` while inventory ACCEPTS the same
source. Fix: delete the hand-written validator; route sqlite field checks through
`row_object_fault` (frame `"row"`, `skip_fields={"observer"}` — the empty/absent observer
class is decided by the stream layer, same as the JSONL arm). After the fix, inventory and
transform must agree on every input (one stream, one verdict) and the module docstring's
"no raw exceptions escape" claim must be TRUE — add the 2**60 case to the seam-defense
tests for BOTH surfaces (inventory refuses it too).

**F2 (gate R2-B2) — delete the regressed compat shims; fix the TESTS, not the constructor.**
`refusals.py`'s `LegacySourceRefused` again accepts 2-/3-/4-element tuples via `len()`
dispatch, plus a dead `absent_observer_spellings` parameter, under `tuple[Any, ...]`.
Production (`legacy_source.py:368`, `:513`) passes only 4-tuples; the 3-tuple arm exists
solely so the STALE tests at `test_refusals.py:53` and `:74` keep passing — which leaves
the spelling data (the substance of the empty-observer fix) untested at the constructor
level. The defect is the stale tests, not the constructor: update both test call sites to
the production 4-tuple shape (asserting the spelling census content), then delete the
`len()` arms, the dead parameter, and the `Any` annotation — one constructor, one precise
tuple type. THE RULE, stated because this is the second regression of the same sweep: when
a shape changes, tests move forward to the new shape; a shim added to keep old tests green
is itself the defect.

**F3 (small, ruled) — residue:** remove the four dead imports the gate counted
(`LegacySourceRefused`/`MigrationRefused` unused in both `inventory.py` and
`transform.py`); do not touch line-length style otherwise.

## Acceptance bar

COMMIT FIRST, then break/restore proofs (paste red → restore → green → empty production
diff):

1. F1: re-introduce the isfinite-only check for sqlite ts → the 2**60 seam test fails on
   both surfaces.
2. F2: re-add a 3-tuple len() arm and revert one test to the 3-tuple shape → the updated
   constructor test fails (the constructor must REFUSE a 3-tuple: paste the TypeError).

Final: `uv run pytest libs/migrate tests/architecture -q` all green; `git status --short`
clean but `.tmp/`; `grep -n "len(item)" libs/migrate/src/migrate/refusals.py` empty.

## Report (stdout, one shot)

Per-fix changes; evidence per proof; found-but-left-alone; honest unverified list.

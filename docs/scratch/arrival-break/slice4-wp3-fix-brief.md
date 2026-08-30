# Slice 4 WP3 — fix round 1 (gate REFUSE ×4 + reviewer ×3, arbiter-ruled; includes two narrow ENGINE edits)

## Working directory — verify FIRST

    /Users/kaygee/Code/loops-wt/s4-wp3

Prefix EVERY command with `cd /Users/kaygee/Code/loops-wt/s4-wp3 && `. First:

    cd /Users/kaygee/Code/loops-wt/s4-wp3 && pwd && git branch --show-current && git log --oneline -1

Expected: branch `slice4/wp3`, HEAD ab9ba7c1. Otherwise STOP and report. Test env:
`TMPDIR=/Users/kaygee/Code/loops-wt/s4-wp3/.tmp` for migrate tests; ANY engine-suite run
uses `TMPDIR=/private/tmp/s4wp3-tmp` (exists) — an engine test asserts the state root is
not under $HOME.

## EXECUTE YOURSELF — DO NOT DELEGATE. One response, no questions.

## Scope fence — WIDER THAN USUAL, exactly bounded

You MAY edit: `libs/migrate/**`, AND exactly these engine surfaces (each in its OWN
commit, first in the sequence):

- E1: `libs/engine/src/engine/arrival.py` — `Entry` gains signature carriage;
  `append_marked_many` stops hardcoding `sig=None`; plus E2's typed torn-tail. Engine
  tests for both under `libs/engine/tests/`.
- `libs/engine/src/engine/arrival_file_backend.py` — `FileLedger.append`'s refusal arm
  for signed drafts (:299-309) is REMOVED; the adapter carries `RecordDraft.signature`
  through; the GRAMMAR judges legality (no new adapter-level checks).

NOTHING else in engine — no other files, no drive-by cleanup there. Never touch
`.loops/`, `~/.local/state`, `~/.config/loops`, or run `sl`/`loops` emit. Quarantine
ratchet + Rule 4 stay true. STOP and report anything more.

These engine edits are RULED (design amendment #2 on
design:arrival-break-slice4-migration-sidecar): the contract append op honors
`RecordDraft.signature`. The gate has already byte-compared append vs the self-coordinated
replicate on unsigned drafts — identical logs — so signature carriage must be
byte-preserving for unsigned drafts (a gate assertion).

## The fixes, in order

**E1 — engine: signature carriage in the batched append path.** `Entry` gains a
`signature: str | None = None` field; `append_marked_many` carries it instead of
hardcoding `sig=None`; `FileLedger.append` stops refusing signed drafts and passes
`d.signature` through. Engine tests: (a) a signed key-introduction draft appends through
the contract op and `verify_authorship` passes over the result; (b) unsigned drafts
produce BYTE-IDENTICAL logs to before the change (fixture comparison); (c) mutation:
revert the carriage (hardcode sig=None again) → test (a) fails.

**E2 — engine: typed torn tail.** `arrival.py:1255` raises a bare `ArrivalError` for a
log ending mid-record while `ArrivalCorrupt` covers complete-but-wrong records — callers
cannot discriminate torn from tampered. Add a narrow typed subclass (e.g.
`ArrivalTornTail(ArrivalError)`; name it a location claim, docstring says what the read
lacks — bytes end mid-record — never a remedy) and raise it there. One engine test pins
the type; mutation: revert to bare ArrivalError → red.

**F1 — sink: admission, not replicate (finding s4wp3-replicate-instead-of-admission).**
Delete `_drafts_to_records` and `_append_drafts_through_wrapper`'s self-coordination;
append `RecordDraft`s through `ledger.append(expected, drafts)` in chunks. The resume
diff already compares draft fields, unaffected (gate-verified).

**F2 — sink: publish cannot no-op (finding s4wp3-publish-silent-noop).**
(a) After re-parse, assert `post_ast.store` equals the target location and
`post_ast.store_backend` the backend — the EDITED fields, currently the only ones
unasserted. (b) Before editing: locate the effective store clause with loader semantics —
refuse (typed, migrate family: "the store clause cannot be unambiguously located for a
surgical edit") when the file holds duplicate `store` nodes, when the regex match count
!= 1, or when the matched line is inside a comment (the two probed evasions). (c) Test 7
gets the wrong-location mutant: an editor writing a wrong path must turn it red
(mutation-verified).

**F3 — sink: resume trusts nothing it didn't derive (finding
s4wp3-resume-genesis-tautology).** Resume verifies the target's genesis against
`genesis_req`: custodian identity AND custodian public key must match what the
declaration derives — a mismatch is a typed refusal naming both identities (location
claim). The ordinal-0 (genesis-only) target is compared as such, not skipped. Test: the
mallory case — resume onto a foreign genesis-only store → refusal; and a genesis-only
target of the RIGHT lineage resumes cleanly. (With F1+E1, admission's authority walk also
runs — keep it as backstop, not substitute.)

**F4 — sink: refusal honesty (finding s4wp3-refusal-types-assert-unchecked).**
(a) Delete `_is_torn_tail_error` and every substring discrimination; catch TYPES:
`ArrivalTornTail` → `TornTailRefused`; `StoreLost` and other seam refusals → a new
`TargetUnopenable` sink refusal that CARRIES the cause and asserts only openness (never
re-typed as mismatch or torn); `ArrivalCorrupt` → its own honest mapping.
`TargetMismatchOnResumeRefused` is raised ONLY by the prefix diff that actually ran.
(b) Widen the storage wrap beyond `sqlite3` errors: `OSError`, `UnicodeDecodeError` per
the slice-3 `read_journal` model — but NEVER a bare `except Exception` re-typed into a
narrower claim; anything unrecognized propagates as itself.
(c) Tests: torn tail → TornTailRefused via the TYPE (assert the engine type in the
cause); tampered-with-valid-length → the corrupt mapping; StoreLost passthrough case →
TargetUnopenable with cause preserved.

**F5 — sink: the F2-resume-diff ratchet (finding s4wp3-f2-resume-diff-unratcheted).** Add
the gate's constructed case: a resume target with a VALID chain whose content diverges
from the source-derived drafts (divergent payload at ordinal 3) → 
`TargetMismatchOnResumeRefused` naming the ordinal, target bytes unchanged. Mutation:
disable the prefix diff (`if False and ...`) → this test goes red (today ALL 11 pass
under that mutation — that is the defect).

**F6 — tests stop polluting the real state root (finding
s4wp3-tests-pollute-real-state-root).** `libs/migrate/tests/conftest.py` with an autouse
fixture redirecting `XDG_STATE_HOME` to the test tmp dir — copy the engine suites'
existing pattern (find it in libs/engine/tests). Verify: run the sidecar suite, then
assert `~/.local/state/loops/heads/` mtime/content unchanged (do this check manually and
paste it; do NOT write a test that reads the real home).

**F7 — ride-alongs, ruled.** (a) The `.vertex` field-equality enumeration dissolves into
a loop over `VertexFile.__match_args__` minus `{store, store_backend, path}` (kills the
drift surface). (b) `verify_migration_report` returns/raises DISTINCT causes (bad
signature / missing target / head mismatch / malformed report); the signed canonical
bytes cover the entire report minus the signature field itself, and the verifier rejects
unknown top-level keys (malleability). (c) The report file is written temp+fsync+replace
like the descriptor. (d) `_check_inventory_equality` actually uses its dropped-units
parameter (today ignored — WP2's dropped_units path is unreachable at the sidecar
surface); add a test migrating with a whole-unit-dropping rule where equivalence and
inventory equality hold WITH the exception accounting, and one with `ulid_migration()`
(the equivalence re-run has never exercised a mapping rule). (e) Remove the 13 unused
imports and the dead `exceptions` parameter.

## Acceptance bar

COMMIT FIRST (E1, E2 as separate leading commits; then sink commits), THEN break/restore
proofs (paste red → restore → green → empty production diff each):

1. E1 mutation (sig=None) → signed-introduction append test red.
2. F2: make the editor write a wrong location → test 7 red.
3. F3: drop the genesis_req comparison → mallory test red.
4. F5: disable the prefix diff → the divergent-payload test red.
5. F4: reintroduce a substring discrimination for torn tail and delete the typed catch →
   the type-asserting test red.

Final checks, paste output: `uv run pytest libs/migrate tests/architecture -q` all green;
`TMPDIR=/private/tmp/s4wp3-tmp uv run --directory libs/engine pytest -q` — reconcile
against the 2304+1s baseline (+ your new engine tests); `uv run --directory libs/store
pytest -q` 180; `git status --short` clean but `.tmp/`; grep shows no
`_is_torn_tail_error`, no `replicate(` in sidecar.py, no self-coordination.

## Report format (stdout, one shot)

Per-item changes; evidence per proof; the engine diffs summarized precisely (they get the
heaviest gate scrutiny); anything you stopped on; found-but-left-alone; honest
unverified list.

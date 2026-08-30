# Slice 4 WP1 — fix round 1 (gate FAIL + reviewer blockings, arbiter-ruled)

## Working directory — verify FIRST

Your workspace is the git worktree at:

    /Users/kaygee/Code/loops-wt/s4-wp1

Every command MUST be prefixed `cd /Users/kaygee/Code/loops-wt/s4-wp1 && `. First action:

    cd /Users/kaygee/Code/loops-wt/s4-wp1 && pwd && git branch --show-current && git log --oneline -1

Expected: branch `slice4/wp1`, HEAD 6e39d84e. If not, STOP and report — editing the wrong tree
is worse than doing nothing. Test env: `TMPDIR=/Users/kaygee/Code/loops-wt/s4-wp1/.tmp` and
pytest `--basetemp=/Users/kaygee/Code/loops-wt/s4-wp1/.tmp/pt`.

## EXECUTE YOURSELF — DO NOT DELEGATE

There is no one to hand this to; if you delegate or stop to ask, the work does not happen.
Deliver everything in one response.

## Context

You are FIXING findings from an independent gate + adversarial review of the WP1 commit
(6e39d84e) in this worktree. You have none of the original implementer's context — everything
you need is in this brief and the code. Each fix below is RULED; implement as prescribed.
If a prescription seems wrong against the code, STOP on that item and report — never
substitute your own design.

## Scope fence

You MAY edit ONLY: `libs/migrate/**`, and exactly one line in
`tests/architecture/test_rule_11_record_never_imports_surfacing.py` (F1), and the `migrate`
row in `tests/architecture/test_rule_04_lib_dependency_dag.py` (F8). NOTHING else — no other
architecture tests, no engine/store/lang/apps/docs edits, no reformatting or cleanup in
passing, never touch `.loops/` or anything outside the worktree, never run `sl`/`loops`
emit commands. If something outside the fence must change, STOP and report it.

## The fixes (implement all, in this order)

**F1 — Rule 11 layer row (gate B1, arbiter-ruled: migrate = record layer).** Add
`"migrate": "record",` to `_LIB_LAYER` in
`tests/architecture/test_rule_11_record_never_imports_surfacing.py:19-27`, matching the
file's style. (The ARCHITECTURE.md half of the rule's message is handled outside your tree —
the file is untracked; do not look for it.)

**F2 — Refusal redesign (reviewer B-1/B-2, gate B2 — one root cause: the copy took engine's
mixed-observer expression and dropped its validate-first precondition).** Rework the
inventory pass's batch handling in `libs/migrate/src/migrate/inventory.py`:

1. **Validate each batch line FIRST** (the frozen copy of `_validate_batch` / row
   validation), exactly as `engine/arrival_body.py:229-238` orders it: validation, then the
   observer decision. A line that fails validation is a CODEC-INVALID line — it must never
   be reported as a mixed-observer batch (probed failures today: nested batch,
   tick-inside-batch, unknown field, duplicate id all misreport as mixed).
2. **Scan the ENTIRE source before raising.** Collect, per offending line, into three
   distinct condition classes: (a) codec-invalid lines (line number + the codec error's own
   message), (b) mixed-observer lines (line number + sorted present-observer set), (c)
   absent-observer lines (line number + count of rows missing the field + the present-
   observer set of the remaining rows). A line exhibiting BOTH mixed and absent aspects is
   reported ONCE with both aspects visible (present observers AND absent-row count) under
   the mixed class — a real GF-3 violation must never be shown to the operator as a
   missing-field problem (gate probe: a line with rows alice, bob, and one observerless row
   reported as AbsentObserver — wrong).
3. **Nothing preempts anything**: one refusal raised at end of scan, enumerating ALL
   offending lines across ALL three classes. No condition ordering can drop another class's
   lines (gate probe: 1 absent + 2 mixed reported only the absent line — wrong). No raw
   TypeError may escape: `observer={"a":1}` or a heterogeneous observer set must land in
   the codec-invalid class with a clean message naming field and type (validation-first
   gives this for free).
4. Keep the existing refusal family and its no-remedy-in-type discipline; the exception's
   structured data grows to carry the three classes distinctly. Update the message to
   present the classes separately. Advisory prose stays in the message only.
5. Update/extend tests: a fixture holding codec-invalid + mixed + absent lines TOGETHER
   (plus legal lines) asserting every offending line appears in the right class; the
   both-aspects line case; the TypeError cases landing as codec-invalid.

**F3 — Frozen-copy fidelity (gate B3).** In `libs/migrate/src/migrate/legacy_jsonl.py:222-226`
restore the origin's exact duplicate-id semantics: `elem["id"]` with unconditional add
(origin: `engine/jsonl_codec.py` — diff the function against origin and make it match,
modulo the docstring-cited reading-only trims). No `.get("id")` weakening.

**F4 — Era census scope-the-claim (gate B4).** `classify_id_era` currently labels every
non-ULID id "uuid4" (empty string, "hello", garbage). Rename that bucket to `other` — the
supportable claim is "not a canonical ULID", not an era verdict. Keep the canonical-ulid and
lowercase-ulid buckets. `SourceInventory` field/docstring and `test_legacy_readers.py:46`
update accordingly (the test currently ENSHRINES the overclaim — it must now pin the honest
bucket).

**F5 — Content-hash claim narrowed (arbiter ruling on reviewer N-1 / gate N1).** The
cross-format hash-equality test (`test_inventory.py` — the jsonl-vs-sqlite equality) DIES:
the two arms hash in different orders (jsonl line-order, sqlite facts-then-ticks) and the
property is false for any interleaved store; it passes by fixture accident. Replace with
per-arm stability tests (same source re-inventoried → same hash; a changed row → changed
hash). Docstrings: `content_hash` is SAME-FORMAT row-content identity only — state each
arm's ordering explicitly, state that it does NOT witness batch grouping (a 2-row batch and
the same rows flat hash identically) and is NOT comparable across formats. Migration
equivalence rests on the re-run diff (WP3), never on comparing these hashes across a format
change. Do not add a structure digest — ruled out.

**F6 — Honest per-arm fields (arbiter rulings O-1, N-2).** `SourceInventory`: split
`total_lines` into `total_rows: int` (both arms, row semantics identical) and
`total_lines: int | None` (jsonl only; `None` for sqlite = "lines are not a concept this
format has"). `batch_line_count` becomes `int | None`: `None` for the sqlite arm — legacy
sqlite cannot represent batch envelopes, and reporting `0` asserts a fact the format cannot
carry (scope-the-claim). Docstrings state absent-is-not-zero for both. Update tests and the
fixture expectation table.

**F7 — Read-only test strengthened (reviewer N-4, mutation-proven weak).** Replace
`test_inventory_module_contains_no_write_calls` (source-text grep — a detection ratchet that
misses mkdir/append/os.*/tempfile and can't see the other modules) with a behavioral test:
recursive snapshot of the source's parent directory (relative paths + sizes + mtimes) before
and after `inventory()`, asserted equal, on BOTH the success path and the refusal path. It
must fail under the probe mutation: `inventory()` mkdir-ing a directory and appending a log
file beside the source (that exact mutation is your break/restore proof #3).

**F8 — Dead code + Rule 4 shrink (arbiter ruling O-6).** Remove the dead code carrying the
package's only `engine` import (find it; the reviewer located the sole engine import in dead
code — also remove `_chain_head` if nothing calls it, it is origin-identical and unused).
Then shrink the Rule 4 row in `tests/architecture/test_rule_04_lib_dependency_dag.py` to
what `libs/migrate/src` ACTUALLY imports after the removal (likely the empty set — write
`"migrate": set()` or the file's idiom for no-deps, with a comment that WP2/WP3 grow it as
real imports land; shrink-only discipline). If removing something breaks a test that
legitimately pins it, STOP on that item and report.

**F9 — Quarantine ratchet (arbiter ruling on gate N2).** New test
`libs/migrate/tests/test_quarantine.py`: walk every module under `libs/migrate/src` with
`ast` (imports, static and `importlib`-free — parse real import statements, never grep
source text) and assert none imports `engine.jsonl_codec`, `engine.jsonl_store`,
`store.rebirth`, or `store._conn`. Module docstring: this ratchet guards the freeze window
until slice 5 deletes those modules, at which point it dissolves (construction supersedes
detection) — slice 5's residue sweep removes it.

## Acceptance bar

COMMIT FIRST (one commit per F-item or sensible grouping, imperative messages), THEN
break/restore proofs against the committed state — paste failing output, restore, paste
green, and paste the empty `git diff` over production paths after each:

1. F2 preemption: re-order the raise so absent preempts mixed → the combined-fixture test
   fails.
2. F2 completeness: make the scan stop at the first offending line → the enumeration test
   fails.
3. F7: apply the mkdir+append mutation to `inventory()` → the read-only test fails.
4. F9: add `import engine.jsonl_codec` to any migrate module → the quarantine test fails.
5. F4: relabel the `other` bucket back to `uuid4` → the era test fails.

Final checks, paste output:
- `uv run pytest libs/migrate tests/architecture -q` — ALL green (Rule 11 included, 113+ passed, 0 failed).
- `git status --short` — nothing unexpected (`.tmp/` only).
- `grep -rn "engine.jsonl\|store.rebirth\|store._conn" libs/migrate/src/` — empty.

## Report format (stdout, one shot)

1. Per F-item: what changed, file by file.
2. Pasted evidence per acceptance check and proof.
3. Anything that seemed wrong with a prescription (stopped, not substituted).
4. Found-but-left-alone outside the fence.
5. What you did not verify — honestly. A gap you name is useful; a papered-over gap costs
   more at the gate.

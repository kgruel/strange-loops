# Slice 4 WP1 — `libs/migrate` + frozen LegacySource + GF-3 inventory-pass refusal

## Working directory — verify FIRST, before anything else

Your workspace is the git worktree at:

    /Users/kaygee/Code/loops-wt/s4-wp1

Every shell command you run MUST be prefixed with `cd /Users/kaygee/Code/loops-wt/s4-wp1 && `
(your shell does not start there). First action:

    cd /Users/kaygee/Code/loops-wt/s4-wp1 && pwd && git branch --show-current && git log --oneline -1

Expected: branch `slice4/wp1`. If the branch or directory is not what is stated here, STOP
immediately and report — do not proceed, do not "fix" it. Editing the wrong tree is worse than
doing nothing.

Environment for every test/uv command (the sandbox blocks writes outside your workspace):
prefix with `TMPDIR=/Users/kaygee/Code/loops-wt/s4-wp1/.tmp` (create the dir first) and run
pytest with `--basetemp=/Users/kaygee/Code/loops-wt/s4-wp1/.tmp/pt`.

## EXECUTE YOURSELF — DO NOT DELEGATE

There is no one to hand this to. If you delegate, the work does not happen. Do every step
yourself, in this session.

## Contract (ratified — deviations are reportable, not decidable)

You implement WP1 of the ratified slice-4 design, `design:arrival-break-slice4-migration-sidecar`
(full proposal: `docs/scratch/arrival-break/slice4-design-proposal.md` in your worktree — read
§A.5, §B, §J.1, §J.2 before writing code). The rulings that bind THIS work package:

1. **GF-3 REFUSE, not split.** A source holding a mixed-observer batch line refuses migration.
   The refusal fires in the **inventory pass** — before any target bytes could exist — and
   **enumerates every offending source line** (file, line number, the observer set found), not
   just the first. Backend-contract §04 ("Backend batching must not rewrite one semantic batch
   into several fact records or vice versa") is ratified as binding the transformer.
2. **The refusal is typed in the sidecar's OWN exception family** — a new root in
   `libs/migrate`. It must NOT subclass or wrap `ArrivalBodyError` and must NOT live under
   `ContractRefusal`. The type asserts what the source carries (a location claim: "these source
   lines carry rows from more than one observer, which this transformer cannot map to one
   record"). The type carries NO remedy. Advisory prose in the *message* may name the operator's
   options; the type name and docstring may not promise any. No configuration flag disables the
   refusal.
3. **Frozen = copy, not import.** The legacy readers are COPIED into `libs/migrate`, trimmed to
   reading, with no import edge back to `engine.jsonl_codec`, `engine.jsonl_store`, or
   `store.rebirth`. No refactors, no de-duplication against the arrival codec, no feature work —
   the copies are historical artifacts and should read as such. Cite the source module and the
   copied-at commit in each copied module's docstring.
4. **Quarantine by birth.** `libs/migrate` is a new workspace package. Rule 4's `LIBS` is
   glob-derived, so the package auto-enrolls; the OUTWARD quarantine (nothing imports migrate)
   is enforced with zero rule edits. You add exactly one inward row and one Rule 7 entry (see
   deliverable 6).

## Scope fence

You MAY create/edit ONLY:

- `libs/migrate/**` (new package — everything under it)
- root `pyproject.toml` — register the new member. Mirror how an existing lib (e.g. `store`) is
  registered EVERYWHERE it appears in that file (workspace members list, and any build/source
  inlining the root wheel does — grep for `"libs/store"` and `store` in the file and mirror each
  hit). Report what you found and mirrored.
- `tests/architecture/test_rule_04_lib_dependency_dag.py` — add the row
  `"migrate": {"engine", "store", "lang"}` (match the file's existing style/comments).
- `tests/architecture/test_rule_07_sqlite3_confined_to_engine_store.py` — add `"migrate"` to
  `_SQLITE_ALLOWED_LIBS`, with a one-line comment naming why (frozen sqlite-canonical reader).

You MUST NOT touch anything else. No edits to `libs/engine`, `libs/store`, `libs/lang`, `apps/`,
`docs/`, other architecture tests, or CI config. No reformatting, import cleanup, or lint fixes
in passing anywhere outside `libs/migrate`. NEVER touch `.loops/`, `~/.config/loops`, or any
file outside your worktree; never run `sl` or `loops` emit/seal commands. If you believe
something outside the fence must change, STOP and say so in your final report instead of doing
it. An out-of-scope edit is a failure of this task even if the edit is good.

## Deliverables

1. **Package skeleton**: `libs/migrate/pyproject.toml` (name `migrate`, deps `engine`, `store`,
   `lang` as workspace sources — mirror `libs/store/pyproject.toml`'s shape, same dev group),
   `libs/migrate/src/migrate/__init__.py`, `libs/migrate/README.md` (three sentences: what the
   sidecar is, the quarantine rule, pointer to the design fact), `libs/migrate/tests/`.

2. **Frozen jsonl-canonical reader** (`src/migrate/legacy_jsonl.py`): copy from
   `libs/engine/src/engine/jsonl_codec.py` the decode surface a reader needs — line → object,
   the `t` dispatch (`records_from_object` and what it calls), fact/tick/batch row shapes.
   Reading only; drop encode paths. The legacy `body.t` knowledge lives HERE from now on.

3. **Frozen sqlite-canonical reader** (`src/migrate/legacy_sqlite.py`): copy from
   `libs/store/src/store/rebirth.py` the reading spine — `_tick_columns`,
   `_facts_have_signature`, `_content_sha256` (the witness-order content hash), `_chain_head`,
   the fact-row iteration out of `_expected_rows` (reading half only), and the file-vs-content
   two-hash distinction with its docstring rationale (`rebirth.py:193-219`). Open the source
   read-only via `sqlite3.connect("file:...?mode=ro", uri=True)` — do not import `store._conn`.
   Also copy `ulid_migration`'s era knowledge (`rebirth.py:106-154`: `is_ulid`,
   `deterministic_ulid`, `ulid_migration`, `identity`, the `Transform`/`FactRow` dataclasses as
   needed) into `src/migrate/legacy_ids.py` — quarantined verbatim, docstring pointing at
   rebirth as origin.

4. **Inventory pass** (`src/migrate/inventory.py`): `inventory(source) -> SourceInventory` over
   both source formats. `SourceInventory` (frozen dataclass) carries: source format
   (`jsonl-canonical` | `sqlite-canonical`), total lines/rows, per-kind row counts, tick count,
   batch-line count, observer census (observer → row count), content hash (witness-order row
   hash), file hash (forensic), and the id-era census (uuid4 / lowercase-ulid / canonical-ulid
   counts — the eras `legacy_ids` knows). The inventory READS ONLY — it never writes, never
   creates any path, never mutates the source (open files read-only; assert no `open(..., "w")`
   anywhere in the module).

5. **The GF-3 refusal** (`src/migrate/refusals.py` + wired into the inventory pass): the
   sidecar's exception root (pick a name that is a location claim about migration, e.g.
   `MigrationRefused` as root — your choice, rationale in the docstring) with the
   mixed-observer-batch refusal as a subclass. Raised by `inventory()` when any batch line's
   row-body `observer` set has more than one member — decided on row bodies exactly as
   `engine/arrival_body.py:241-266` decides it (copy that decision rule's semantics, not its
   code path). The exception carries structured data: a tuple of (line number, sorted observer
   set) for EVERY offending line. Rows *missing* the observer field are a different condition —
   report them in the exception's data distinctly (absent is not an observer; do not fold
   `None` into the observer set as if it were an author). Message: the location claim + the
   full enumeration + advisory prose naming the operator's options (repair the source by hand /
   re-run after a ruled re-ceremony); NO remedy in the type or its docstring.

6. **Architecture rule edits**: the Rule 4 row and Rule 7 entry named in the scope fence.
   Both suites must pass: `cd <wt> && TMPDIR=... uv run pytest tests/architecture -q`.

7. **Tests** (`libs/migrate/tests/`), including a fixture builder (`tests/_fixtures.py`) that
   constructs synthetic legacy sources in a tmp dir, parameterized over both formats where
   meaningful. Minimum:
   - inventory counts vs HAND-COMPUTED expectations on a fixture with facts across all three id
     eras, signed and unsigned rows, ticks, and single-observer batch lines;
   - the mixed-observer refusal: a jsonl fixture holding TWO mixed-observer batch lines (build
     them like `test_arrival_body.py:157-167` does — the line codec permits them) → `inventory()`
     raises the typed refusal, the exception's data names BOTH lines with their observer sets,
     and no path was created anywhere by the call;
   - a batch line with a row MISSING the observer field → reported as the distinct
     absent-observer condition, not as a mixed batch;
   - the two-hash distinction: content hash stable across a byte-level rewrite that preserves
     rows (e.g. re-write the jsonl with different key ordering is NOT possible for jsonl — for
     the sqlite arm, VACUUM changes the file hash but not the content hash);
   - read-only: after every inventory call in the suite, the source bytes are unchanged
     (compare digests).

## Acceptance bar — proof the tests can fail

COMMIT YOUR WORK FIRST (normal commits on `slice4/wp1`, clear messages), THEN run break/restore
proofs against the committed state. For each proof: break the production behavior, run the
test, paste the failing output, `git restore` the file, re-run, paste green. A `git diff` that
is empty because nothing was uncommitted is not evidence — the commit-first order is mandatory.

1. Remove the mixed-observer check from the inventory pass → the refusal test fails.
2. Make the refusal report only the FIRST offending line → the enumeration test fails.
3. Perturb one inventory count (off-by-one) → the hand-computed test fails.
4. Add `import migrate  # rule-4 probe` to any `libs/engine` module → Rule 4 fails (this proves
   the outward quarantine is live with zero rule edits). Revert.
5. Fold a missing observer into the observer set as `None` → the absent-observer test fails.

After all proofs: `cd <wt> && git status --short` must show nothing unexpected, and
`git diff` over all production paths must be EMPTY. Paste both.

Final checks, paste output: `uv run pytest libs/migrate tests/architecture -q` green;
`grep -rn "from engine.jsonl\|import engine.jsonl\|from store.rebirth\|from store import.*rebirth\|from store._conn\|import jsonl_codec\|import jsonl_store" libs/migrate/src/` returns NOTHING.

## Report format (stdout, one shot — do not stop to ask anything)

1. What changed, file by file.
2. Pasted evidence for every acceptance check and break/restore proof.
3. Root-pyproject registration: what you found and mirrored.
4. Deviations from the contract above, if any, with rationale — report, never silently decide.
5. Found-but-left-alone: anything outside the fence that looked wrong.
6. What you did NOT verify. Be honest about what you did not verify. A gap you name is useful;
   a gap you paper over will be found at the gate and will cost more.

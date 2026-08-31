# Slice 4 WP4 — adversarial review report

Reviewer worktree: `/Users/kaygee/Code/loops-wt/s4-wp4-review` (detached at `e1de3a4b`, verified).
Target: `e1de3a4b feat(cli): loops store migrate verb + staged verb dispositions (slice4 WP4)`.
Diff read: `git diff main...HEAD` — 5 files, +306/−10.
Probes: all under `<worktree>/.tmp` (untracked); tracked tree clean throughout; two temporary
mutations of `libs/migrate/src/migrate/sidecar.py` applied and restored (verified by `git diff --stat`
empty). No commits, no store facts emitted, real `~/.config/loops` never touched (`LOOPS_HOME`
pointed at a sandbox for every resolution probe).

Ranges read:
- `apps/loops/src/loops/commands/store.py:37-49` (`_refuse_store`), `:264-308` (`_resolve_target`),
  `:742-860` (`_run_migrate`), `:889-905` (`_run_reanchor` + marker), `:1197-1210`
  (`_absorb_genesis_mode` + marker), `:1905-1920` (dispatcher), `:2010-2020` (base-inspect prose)
- `apps/loops/src/loops/cli/store_args.py:1-62`; `apps/loops/src/loops/commands/init.py:466-485`
- `apps/loops/tests/test_store_migrate.py:1-150`; `apps/loops/tests/test_store_completion.py:40-55`
- `libs/migrate/src/migrate/sidecar.py:1-60, 672-1058`; `libs/migrate/src/migrate/refusals.py:1-316`
- `libs/custody/src/custody/signing.py:1-155`; `libs/engine/src/engine/arrival.py:636-670, 900-960, 1930-2035`
- `libs/migrate/tests/test_sidecar.py:60-90, 195-215, 600-620`
- `docs/scratch/arrival-break/slice4-design-proposal.md` §F

Suites (this worktree, workspace-root form):
- `uv run pytest apps/loops -q` → **2533 passed, 1 xfailed**
- `uv run pytest libs/migrate tests/architecture -q` → **159 passed**

---

## BLOCKING

### B1 — `--vertex` is silently dropped under a vertex context; the wrong store gets migrated

`_run_migrate` resolves its target with `_resolve_target(args.vertex, vertex_path)`
(`store.py:785`). `_resolve_target` returns `vertex_path` **first**, ignoring `file_arg` entirely
(`store.py:276-277`). Every neighbouring store verb feeds a *positional* through that precedence;
migrate is the first to feed a **named flag**. So under the tier-3 vertex route the flag that names
which `.vertex` gets rewritten is discarded with no refusal and exit 0.

Probe — real CLI, tier-3 route:

```
$ loops ctxv store migrate .loops/legacy.jsonl --vertex other/othv.vertex --rule identity
✓ legacy.jsonl → ctxv: migrated (rule=identity)
  lineage: 01M1ARGT4ESEWKVWXWBRNF4J9T · head 1 01bdc5dc4c6e0b86…
  target: 01M1ARGT4ESEWKVWXWBRNF4J9T.arrival
  report: 01M1ARGT4ESEWKVWXWBRNF4J9T.migration-report.json
--- AFTER ---
ctxv store: store "./01M1ARGT4ESEWKVWXWBRNF4J9T.arrival" backend="file"
othv store: store "./legacy.jsonl"
```

The user named `othv`; `ctxv` was migrated and repointed; `othv` untouched; exit 0. The success line
even prints `→ ctxv`, a vertex the user never typed.

This is a direct violation of the wave principle recorded in
`apps/loops/src/loops/cli/refusals.py:3-5` — *"the cli-honesty-wave refuses flags rather than
silently dropping them (honor-or-refuse)"*. For a read-only verb an ignored target flag is a
cosmetic bug; for the one verb whose entire effect is rewriting a `.vertex` store clause it means
migrating a store the operator did not name. Fix is a refusal when both `vertex_path` and
`args.vertex` are present and disagree, not a precedence change.

Not visible to acceptance: no test invokes `_run_migrate`/`_dispatch_store` with both a
`vertex_path` and a `--vertex`.

### B2 — the documented `--vertex` default is structurally unreachable, and refuses with a claim about something the user never typed

`--vertex`'s help promises *"default: resolve like other store verbs"*. With the flag omitted,
`_resolve_target(None, None)` falls through to `<LOOPS_HOME>/.vertex` (`store.py:302-305`) — the
global config root, independent of cwd (`loops_home()` reads `$LOOPS_HOME`/`$XDG_CONFIG_HOME`, it
does not walk up from cwd). That path is a dotfile, so:

```
/h/.vertex           suffix=''  stem='.vertex'
/h/alice.vertex      suffix='.vertex'  stem='alice'
```

and the guard at `store.py:786-790` (`if vertex_target.suffix != ".vertex"`) rejects it every time.
Probe — real CLI, `LOOPS_HOME` sandboxed, cwd unrelated:

```
$ loops store migrate legacy.jsonl --rule identity
migrate requires a .vertex target — the custodian signer and observer registry
live in the custody context, not a raw .db
--- ROOT VERTEX store clause AFTER ---
store "./legacy.jsonl"
```

Two problems, one line. First, brief requirement 1 is unmet: the flagless form advertised in the
help can never succeed — `--vertex` is de-facto mandatory and is not declared `required=True`.
Second, the refusal makes a verdict claim about *"a raw .db"* when no `.db` is in play; the actual
condition is "the resolved default target is not a suffixed `.vertex`". That is the
scope-the-claim-over-widen-the-detection rule applied to a refusal message — the message should
name the location ("no `--vertex` given and the resolved root `<path>` is not a `.vertex` target"),
not a genus the operator never invoked.

The safe half is accidental, not designed: the ambient global-root default *would* repoint the
user's root vertex from any cwd, and the only thing stopping it is that `Path(".vertex").suffix`
happens to be `''`. Whichever way this is fixed, the fix should be deliberate.

Not visible to acceptance: no test exercises the `--vertex`-omitted path.

### B3 — the arrival attestation layer is signed under the *fact* domain; domain separation is collapsed

`_run_migrate` builds its custodian signer with `from custody import fact_signer_for`
(`store.py:795-797`). That signer signs under `FACT_DOMAIN = "loops-fact-v1"`
(`custody/signing.py:31, 149-153`) — the domain for **inner fact-content** signatures. There is no
arrival-specific domain anywhere in product code (`ARRIVAL_DOMAIN` exists only as a test-local
constant, `libs/migrate/tests/test_sidecar.py:67`, paired with a matching test verifier, so the
sidecar's own suite is self-consistent and cannot see this). WP4 is the first product construction
of an arrival `Signer`, and it silently answers a question no ruling has answered.

Probe — migrate through the CLI, then re-derive the genesis commitment:

```
genesis observer      : alice
genesis commit digest : 968757e176c92980858c8ef4159741ef600d8045b967c72538971099209b43d8
genesis signature     : 95xCktbjwIWl/xzSCXPcKCQRRLCYyGOJ/QrGHOy/2grO ...

  sign under loops-fact-v1 (FACT_DOMAIN)      matches genesis sig? True
  sign under loops-tick-v1 (TICK_DOMAIN)      matches genesis sig? False
  sign under no domain / arrival-specific     matches genesis sig? False

--- CROSS-PROTOCOL ACCEPTANCE ---
Does fact_verifier_for(...) accept the ARRIVAL GENESIS signature as a valid
'fact' signature by observer 'alice' over the same digest?  -> True
Conversely, an ordinary fact signature over that digest equals the
arrival genesis signature bit-for-bit? -> True
```

It is not only genesis. With three declared observers the whole registry-forming layer is affected:

```
records: [(0,'genesis','alice'), (1,'key','alice'), (2,'key','alice'), (3,'fact','alice'), (4,'fact','bob')]
key-introduction records: 2
  intro of 'bob':   envelope observer='alice' | sig == custodian's loops-fact-v1 signature? True
  intro of 'carol': envelope observer='alice' | sig == custodian's loops-fact-v1 signature? True
```

Scoping the claim honestly: this is **not** a forgeable-today hole. `verify_authorship` has **no
product caller** (grep over `apps/*/src libs/*/src`: definition and docstrings only), so nothing
currently verifies these signatures, and the two digest preimages differ in shape, so exploitation
would need a preimage collision. What is real: the cryptographic separator whose *job* is to make
that shape-difference irrelevant has been removed, by import choice rather than by ruling, and
`custody/signing.py`'s own header documents domain separation as that module's discipline (TICK vs
FACT were split for exactly this reason — arrival envelopes are a third message genus reusing the
second's domain).

Why blocking rather than deferrable: genesis signatures are **persisted, signed artifacts**. Every
store migrated before this is settled carries a fact-domain attestation root, and correcting it
later means re-minting those lineages, not patching code. This is the twin-resolvers hazard at its
most expensive point. It needs either a ruled `ARRIVAL_DOMAIN` + an arrival signer constructor in
`custody`, or an explicit ruling that the fact domain is the arrival domain — but not silence.

---

## Non-blocking

### N1 — the e2e test does not assert *which* store the `.vertex` now names

`test_migrate_through_cli_mints_lineage_and_updates_descriptor` checks only
`post_ast.store_backend.name == "file"` (`test_store_migrate.py:107`). Mutation probe — make the
sidecar publish a location that is not the target at all:

```python
edit_vertex_store_clause(vertex_path=v_path,
                         target_location="./WRONG-NOT-THE-TARGET.jsonl", backend="file")
```
```
3 passed in 0.09s
```

A catastrophic publish bug passes the whole WP4 module. The complementary mutation (skip publish
entirely) *is* caught, but incidentally — by `AttributeError: 'NoneType' object has no attribute
'name'`, because a bare `store "./legacy.jsonl"` clause parses to `store_backend=None`, not by an
assertion that says what it means.

Mitigation: the load-bearing assertion exists one layer down —
`libs/migrate/tests/test_sidecar.py:206-208` asserts
`Path(resolved_desc.location).resolve() == outcome.target_path.resolve()`. So behavior is covered;
the CLI test is simply weaker than it reads. Also unasserted at the CLI: the target is never opened
through a real read path (only `.exists()` and a filename pattern), so a minted-but-unreadable
target would pass. One line — `assert (vpath.parent / post_ast.store).resolve() == target_path` —
closes it.

### N2 — re-running migrate on an already-migrated vertex silently repoints it and orphans the live lineage

Probe (CASE 3): two runs of the same command, no `--resume`.

```
arrivals after 1st: ['01M1AR9RJZAA8CS8KSVBHCAA83.arrival']
arrivals after 2nd: ['01M1AR9RJZAA8CS8KSVBHCAA83.arrival', '01M1AR9RK1K6NT4WCE9SX7K051.arrival']
FRESH-MINTED a NEW lineage (never adopted)? True
```

The contract half is correct and worth recording: without `--resume` the sidecar fresh-mints a new
lineage and **never** adopts the abandoned staging target — "resuming is deliberate, never
inferred" holds. The CLI half is the concern: the second run repoints the `.vertex` from lineage A
to lineage B and says nothing. Anything appended to lineage A since the first migration is now
orphaned. There is no "this vertex is already on an arrival lineage" guard at the verb. Sidecar-
owned by contract (abandoned attempts are read-only evidence), but the CLI is where a human
triggers it twice.

---

## Observations

- **O1** `--resume <nonexistent>` exits **1**, not 2. The sidecar raises `FileNotFoundError`
  (`sidecar.py:794`), which is not a `MigrationRefused`, so it falls to the app's top-level
  handler and renders message-only: `Resume target does not exist: …`. Clean output, no traceback,
  and consistent with how neighbouring verbs render a missing target (`store verify nosuch.vertex`
  → same message shape, exit 1) — but every *typed* refusal from this verb exits 2. Minor
  exit-code inconsistency for a condition that reads like a refusal.
- **O2** `_run_adopt` carries no `# slice-5:` marker although §F rules on it ("the genesis-claiming
  half dies; the descriptor half is slice 5's to build"). The brief asked for exactly three
  markers, so this is not a deviation — noting it because a slice-5 reader grepping `# slice-5:`
  will find two of the three ruled verb dispositions.
- **O3** The `--rule` flag genuinely changes the transform, verified through a real read path
  rather than the report: `identity` → `['c56a4180-65aa-42ec-a945-5fd21dec0538', …]`;
  `ulid-migration` → `['000000YGJ0QRG9GJSYVW6JSH6Z', '000000YHH8KFE0SMET5RVK6G02']`.

---

## Verified clean (hunted, no defect found)

- **Refusal-catch breadth (hunt 3).** The clause is exactly `except MigrationRefused as exc`
  (`store.py:820-821`) — no bare `except`. Probe: a `KeyError` injected into `run_migration`
  produced a full traceback through the real CLI, ending at
  `sidecar.py:760 KeyError: 'simulated internal bug — not a refusal'`. Bugs stay distinguishable
  from refusals; the seam makes no verdict claim.
- **Wrong-lineage resume.** `--resume` against an unrelated target refuses cleanly at exit 2, one
  line, no traceback: `✗ alice: Target at …arrival genesis public key '…' does not match expected
  custodian public key '…'. Advisory: start a fresh migration.`
- **Mismatched-rule resume.** Resuming an `identity` target with `--rule ulid-migration` refuses
  (exit 2, "Target record at ordinal 1 diverges from expected deterministic draft") rather than
  producing a half-identity/half-ulid target.
- **Resume of a complete target** is idempotent: no new lineage minted, re-verifies and
  re-publishes, exit 0.
- **Staged markers (hunt 6)** are comment-only — diff-verified, zero behavior lines in
  `init.py`/`_run_reanchor`/`_absorb_genesis_mode` — and are faithful paraphrases of §F's ruled
  dispositions (compared line by line against the §F table). All three sit *above* their function's
  docstring; probed that `__doc__` survives on all three (comments are not statements), so help
  text is unaffected.
- **Count/name sweep (hunt 7).** No stale "nine" references remain in `apps/loops/src`,
  `apps/loops/tests`, `libs/*/src`, or top-level docs. The three lockstep surfaces
  (`STORE_SUBCOMMANDS`, dispatcher, base-inspect prose) all carry `migrate`; the completion-parity
  test passes. Remaining `reanchor` mentions in `docs/UPGRADING.md:177,584` are historical
  changelog entries, not surfaces this change made wrong.
- **`--json`** renders and round-trips (`dataclasses.asdict` over `Head` and `TransformExceptions`).
- **Legacy source is never mutated** (asserted in the e2e test and re-confirmed in probes).

---

## Not verified — honest list

- **sqlite legacy sources.** Every probe used `.jsonl`. The `.sqlite` branch of the verb is
  untouched by me and uncovered by the WP4 test module.
- **Whether the ulid-migration ids are *correct*** per WP2's specification — only that they differ
  from identity and are ULID-shaped.
- **The migration report's own signature domain** in practice: `verify_migration_report` takes an
  injected `verify` and has no product caller, so I did not establish what will verify it.
- **Scale and performance** — largest probe store was 4 rows.
- **Concurrency** — two migrations racing the same `.vertex`, and the `os.replace` publish under
  contention.
- **Non-macOS behavior**, permission-denied paths, and the journal pre-flight failure branch.
- **The apps-pyproject `migrate` dependency gap** — excluded by the brief; the gate owns it. I note
  only that every probe ran from the workspace root, where the dependency resolves regardless.
- **`loops init`'s marked call site** — I read the marker but did not run `loops init` end-to-end.
- Whether any **already-migrated live store** exists that B3 would force a re-mint of.

# Slice 4 WP4 — implementation report

Worktree: `/Users/kaygee/Code/loops-wt/s4-wp4`, branch `slice4/wp4`, base commit
`a5800a0c` (docs-only, contains the brief itself). Final commit `e1de3a4b`.

## Step 0 verification

`libs/migrate/src/migrate/sidecar.py` exists with `run_migration` at line 672
(the header's `libs/migrate/sidecar.py` path is shorthand — the body's exact
path `libs/migrate/src/migrate/sidecar.py` is correct and present). Base not
stale. `libs/migrate/src/migrate/refusals.py` present with the full
`MigrationRefused` family (`MigrationRefused` at line 103, 17 subclasses).

## Changes, file by file

**`apps/loops/src/loops/commands/store.py`** (+138 lines)
- New `_run_migrate(argv, *, vertex_path=None) -> int`, inserted between
  `_run_rebirth` and `_run_export`. Positional `source` (legacy
  jsonl/sqlite), `--vertex` (resolved via the existing `_resolve_target`
  chokepoint, same precedence every other verb uses), `--rule
  {identity,ulid-migration}` (default `ulid-migration`, matching rebirth's
  default choice shape), `--resume TARGET` (maps to `resume_target=`,
  default `None` — never inferred), `--json`.
- Custodian signer: `custody.fact_signer_for(vertex_target)` — the same
  construction `_run_reanchor`/`_absorb_genesis_mode` already use, resolving
  the flat `<vertex dir>/keys/ed25519.key` self-observer layout. Added a
  guard for `signer is None` (no keys directory at all) that returns a clean
  refusal rather than letting `run_migration` crash on a None callable —
  mirrors `_absorb_genesis_mode`'s existing `signable` check precedent, not
  a new privileged path.
- Refusal rendering: single `except MigrationRefused as exc: return
  _refuse_store(str(exc), label=...)` around the `run_migration` call —
  catches the whole family at its base class, consistent with how
  `_run_reanchor`/`_absorb_genesis_mode` catch `JsonlCanonicalUnsupported`/
  `GenesisExists`/`UnsignableGenesis` inline. Untyped exceptions
  (`FileNotFoundError` for a missing source/vertex, `ValueError` for a
  non-`.vertex` target) are raised directly and traceback, same as every
  neighbouring verb.
- `store_dir=vertex_target.parent` — the vertex-adjacent directory, matching
  the existing `keys_dir_for`/`canonical_store_path` convention (both derive
  from `vertex_path.parent`). Not stated explicitly in the design doc; this
  is the one place I made a judgment call rather than finding a pinned
  answer — flagged below as an honest-unverified item.
- `_run_store`'s dispatcher (`_dispatch_store`) gained `if argv and argv[0]
  == "migrate": return _run_migrate(...)` right after the `rebirth` line.
- Base-inspect `description=` prose gained a `loops store migrate ...` line
  in the same enumerated style as the other verbs.
- Two comment-only slice-5 disposition markers, zero behavior change:
  - Top of `_run_reanchor` (before its existing docstring — Python still
    resolves the string literal as `__doc__` with a comment preceding it):
    "reanchor dies outright — no ceremony successor... Ruled disposition:
    design:arrival-break-slice4-migration-sidecar §F."
  - Top of `_absorb_genesis_mode`: "absorb-genesis dissolves into the
    sidecar's mint... under arrival there are no genesisless stores... Ruled
    disposition: design:arrival-break-slice4-migration-sidecar §F."

**`apps/loops/src/loops/commands/init.py`** (+5 lines, comment only)
- Marker above the `_run_absorb([])` call site in `cmd_init` naming
  `loops store migrate`'s sidecar mint as its slice-5 successor. No
  behavior touched.

**`apps/loops/src/loops/cli/store_args.py`**
- `STORE_SUBCOMMANDS` gained `"migrate"` (positioned after `"rebirth"`,
  matching where the dispatcher's new `if` line landed).
- `add_store_args`'s help string updated to list `migrate`.
- Module-docstring residue swept in the same file: "nine per-subcommand
  parsers" → "ten", missing `_run_migrate` added to the enumerated list,
  and "complete the nine subcommand names" → "ten" further down. These were
  stale the moment `STORE_SUBCOMMANDS` grew, so I fixed them rather than
  leaving new drift — all inside a file already in scope.

**`apps/loops/tests/test_store_completion.py`**
- Added `"_run_migrate"` to the monkeypatch-and-count dispatch-parity list
  in `test_every_subcommand_actually_dispatches`, in dispatcher order.
- Left one pre-existing stale docstring alone (`test_first_slot_...`'s "the
  seven names are the whole candidate set" — already wrong before my change
  at nine subcommands; not something my change caused, noted under
  found-but-left-alone).

**`apps/loops/tests/test_store_migrate.py`** (new, 3 tests)
- Module-scoped `autouse` fixture isolating `XDG_STATE_HOME` to `tmp_path`
  (apps/loops/tests had no existing isolation for it; migrate's head
  journal reads it via `engine.arrival_head_attestation.heads_dir()`, same
  posture `libs/migrate/tests/conftest.py`'s autouse fixture uses — scoped
  to this module only, not the shared root conftest, per the brief).
- `test_migrate_through_cli_mints_lineage_and_updates_descriptor`: builds a
  signed `alice.vertex` (flat self-observer key layout) + a 2-row synthetic
  legacy jsonl, calls `_run_migrate([...], vertex_path=None)` through the
  `--vertex` flag (exercises the full argparse + `_resolve_target` path,
  not just a pre-resolved `vertex_path=` kwarg), asserts exit 0, target
  `.arrival` + report exist, `.vertex` store clause updated to
  `backend="file"`, legacy source bytes unchanged.
- `test_migrate_refuses_mixed_observer_batch_before_target_exists`: a
  constructed mixed-observer batch line (GF-3's fixture shape), asserts
  non-zero exit, non-empty stderr, and — the actual assertion this test is
  for — **no `.arrival` or `.migration-report.json` file exists anywhere
  under `tmp_path` afterward**, proving the refusal fires in the inventory
  pass before any target bytes exist.
- `test_resume_requires_its_argument`: `--resume` with no value raises
  `SystemExit(2)` from argparse itself (no custom code needed — this is
  argparse's default behavior for a value-taking flag given no value).

## Break/restore proofs (all COMMIT-FIRST, all real red→green, all restored to an empty diff)

**Proof 1 — remove `migrate` from `STORE_SUBCOMMANDS` only.**
Red:
```
AssertionError: assert ('verify', 'r...'absorb', ...) == ('verify', 'r... 'adopt', ...)
At index 2 diff: 'migrate' != 'reanchor'
Left contains one more item: 'reindex'
FAILED apps/loops/tests/test_store_completion.py::TestStoreSubcommandsParity::test_matches_run_store_dispatch_chain
1 failed, 8 passed in 0.06s
```
Restored via `git checkout -- apps/loops/src/loops/cli/store_args.py`; full
completion file green (`9 passed`); `git diff` on the file empty.

**Proof 2 — swallow the refusal, `return 0` instead of `_refuse_store(...)`.**
Red:
```
    rc = _run_migrate([str(source), "--vertex", str(vpath)], vertex_path=None)
    assert rc != 0
E   assert 0 != 0
FAILED apps/loops/tests/test_store_migrate.py::TestMigrateEndToEnd::test_migrate_refuses_mixed_observer_batch_before_target_exists
1 failed, 2 passed in 0.07s
```
Restored by hand to the exact committed line; migrate test file green
(`3 passed`); `git diff` on the file empty.

**Proof 3 — break the signer loading (point `fact_signer_for` at a
nonexistent sibling directory instead of the real vertex path).**
Red (happy-path e2e test, which is the one that actually exercises signing):
```
    rc = _run_migrate([...], vertex_path=None)
    assert rc == 0
E   assert 2 == 0
Captured stderr call:
✗ alice: no signing key for the vertex's self-observer — migration must sign
the custodian genesis and key introductions (loops add <vertex> observer --keygen)
FAILED apps/loops/tests/test_store_migrate.py::TestMigrateEndToEnd::test_migrate_through_cli_mints_lineage_and_updates_descriptor
1 failed in 0.06s
```
Restored by hand to the exact committed line; migrate test file green
(`3 passed`); `git diff` clean.

Note on proof 3's shape: `ledger.verify(Full(...))` (the file backend's
verify, `libs/engine/src/engine/arrival_file_backend.py:660`) checks
grammar/density/lineage/hash-chain only — it does **not** check
signatures/authority (verified by reading it). So a signer that returns a
*wrong* signature would sail through `run_migration` undetected; the only
way to make signing failure observable at this layer is a signer that isn't
constructible at all (no key material), which is exactly what a wrong key
path produces. That's why I added the `signer is None` guard rather than
leaving it to crash with a raw `TypeError` inside the sidecar — the guard
is what proof 3 actually exercises, and it's an honest, typed failure
mode rather than a bare crash.

## Final checks

`uv run pytest apps/loops -q` from the worktree root (workspace-root form,
never `--directory`):
- **Pre-change (base commit a5800a0c, changes stashed): 2530 passed, 1
  xfailed.**
- **Post-change (committed e1de3a4b): 2533 passed, 1 xfailed.**
- Reconciliation: +3, exactly the three new tests in
  `test_store_migrate.py`. No regressions, no other count drift.

`uv run pytest libs/migrate tests/architecture -q`: **159 passed**, untouched
green, both before and after the break/restore proofs.

`git status --short`: clean except `.tmp/` (pytest basetemp scratch dir, not
tracked, not part of any commit).

## Stopped on

Nothing. Both explicit STOP conditions in the brief came back negative:
- Base staleness check (sidecar.py/run_migration present) — not stale.
- Rule 15 allowlist growth — verified false. `commands/store.py` and
  `commands/init.py` are both **whole-file exceptions** in
  `tests/architecture/test_rule_15_apps_import_only_sdk_and_painted.py`
  (not a per-import allowlist), so a new `import migrate.*`/`from migrate
  import ...` inside `commands/store.py` requires no allowlist edit. `LIBS`
  in that test is computed dynamically from workspace members, so `migrate`
  (a WP1 addition) is automatically in the forbidden set for apps that
  aren't exempted — irrelevant here since the whole file already is.

## Found-but-left-alone

- `apps/loops/pyproject.toml`'s `dependencies` list (`["lang", "atoms",
  "engine", "custody", "sign", "store", "painted"]`) does **not** include
  `migrate`, even though `libs/migrate` is a `[tool.uv.workspace]` member.
  Empirically, `import migrate` already works today inside the worktree
  (`uv run --project apps/loops python -c "import migrate"` succeeds) —
  because this is a uv workspace with one shared virtualenv, every member
  is importable regardless of whether a sibling declares it as an explicit
  dependency. That's real but not the same as `apps/loops` being a
  *correct* standalone dependency graph: anyone who builds/installs the
  `loops` package in isolation (a real venv from a wheel, not the workspace
  dev environment) would hit `ModuleNotFoundError: migrate` at the first
  `from migrate... import ...` inside `_run_migrate`. `pyproject.toml` is
  not in my scope fence (only `commands/store.py`, `commands/init.py`
  comment-only, `cli/store_args.py`, `apps/loops/tests/**`), so I did not
  touch it. **This should be fixed before slice 4 ships** — add `"migrate"`
  to `apps/loops/pyproject.toml`'s `dependencies` — but it's a one-line
  change someone with pyproject.toml in scope should make, not me.
- `test_store_completion.py`'s `test_first_slot_offers_closed_choices_not_files`
  docstring still says "the seven names are the whole candidate set" — this
  was already stale before my change (nine subcommands existed, not seven);
  I didn't touch it since it predates and is unrelated to this slice's
  change, and fixing unrelated pre-existing drift felt like scope creep in
  a test file I'm otherwise only extending narrowly. Flagging it here
  instead.

## Honest unverified list

- `store_dir=vertex_target.parent` for the migrate verb: not pinned
  anywhere in the design proposal (§F/§J.1/§D.2 describe the staging
  target's *name* — lineage-named — but not which directory holds it at
  the CLI layer). I chose the vertex's own directory by analogy to
  `keys_dir_for`/`canonical_store_path`, both of which resolve relative to
  `vertex_path.parent`. This is my judgment call, not a verified-against-
  source answer, and it's the one place in this WP where "verify the exact
  signature in source, it is authoritative over this prose" didn't have
  prose to check against for the CLI's own directory choice.
- I did not write a golden/snapshot test for `_run_migrate`'s text (non-JSON)
  rendering — §L.4 explicitly says no golden net exists for absorb/genesis/
  adopt/reanchor renderings and warns not to rely on one; I read that as
  covering migrate's own new rendering too, so I left the human-readable
  output path exercised only implicitly (the JSON-mode assertions cover the
  outcome's actual field values; the text-mode `paint(...)` call path in
  `_run_migrate` is not separately unit-tested). If a golden net is wanted
  for the text rendering, that's an addition, not a gap I found already
  covered.
- I did not exercise `--resume` end-to-end (only its "requires an argument"
  parse-error edge) — a full kill/restart round trip through the CLI would
  duplicate `libs/migrate/tests/test_sidecar.py::test_kill_mid_append_restart_byte_identical`
  at the CLI layer, which the brief's acceptance bar (5c) only asks to
  prove *argument handling*, not the underlying restart mechanics (already
  proven in WP3). I read that scoping as deliberate but flag it as a choice,
  not a verified brief requirement.

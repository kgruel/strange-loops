# Slice 2 / WP4 report — KDL backend arm + registry + parity probe

Branch: `slice2/wp4-kdl-registry`, off the wave branch tip `0d38c969`
(`git merge-base HEAD slice/arrival-backend-contract` = `0d38c969`, verified at step 0).
Worktree: `~/Code/loops-s2wp4`. Contract: `docs/scratch/arrival-break/slice2-wp4-brief.md`;
design `slice2-design-proposal.md` §B (all four) + §D.4.

Written as the work lands, not after.

## Baseline at 0d38c969 (before any edit)

| Suite | Command | Result |
|---|---|---|
| lang | `uv run --package lang pytest libs/lang/tests -q` | 655 passed |
| engine | `uv run --package engine pytest libs/engine/tests -q` | 1989 passed, 1 skipped |
| architecture | `uv run pytest tests/ --ignore=tests/chaos -q` | 99 passed |

## Commit (a) — the lang half

`lang/ast.py`, `lang/loader.py`, `lang/document.py`, `lang/__init__.py`, and the two
lang test files.

**Counts: lang 655 → 670 (+15), every delta accounted:**

- +7 — `TestStoreBackend` in `test_loader.py`: bare store parses with no backend;
  store+backend parses; backend is NOT cross-checked against the suffix; unknown
  property refused; child block refused; empty `backend=""` refused; blank
  `backend="   "` refused.
- +7 — `BACKEND_DECLARED` joins `SYNTH_CASES`, so all 7 batteries parametrized over
  `ALL_CASES` now run the arm (round-trip via documents, via genesis, idempotence,
  order-after-shuffle, and the diff/apply add/edit/remove family).
- +1 — `test_backend_survives_the_document_round_trip` in `test_document.py`.

### Design choices

- **`store_backend` sits immediately after `store` in `VertexFile`**, not at the end.
  The two are one residence pair and read as one. Safe because nothing constructs
  `VertexFile` positionally and nothing pattern-matches it positionally (checked:
  no `case VertexFile(`, and all 5 production + 6 test construction sites use
  keywords) — `ast.py`'s `_frozen` builds `__match_args__` from field order, so this
  was worth checking rather than assuming.
- **`VertexFile.store` is untouched**, which is what keeps the ~20 existing readers
  and `canonical_mode` dispatch byte-identical through slice 4.
- **The grammar admits any non-empty backend name.** An unregistered name is refused
  at *open* time by the registry, not at parse time, so a vertex naming a backend
  another deployment provides still parses. Refusing at parse time would make the
  grammar a registry.
- **No suffix cross-check**, pinned by its own test. Once the backend is declared the
  suffix carries no meaning (§02); a "does the suffix agree?" check would re-admit
  inference through the back door on the change that removes it.
- **Empty `store "…" { }` is not refused** — CKDL normalizes an empty child block to
  no children, so the loader cannot distinguish it from the no-block case. Identical
  to the known limitation already documented for `preview` in `test_loader.py`. It
  declares nothing, so nothing is silently discarded. Noted at the refusal site.
- **`documents_to_vertex(..., store_backend=)` is a third residence parameter**, not a
  field read from documents. Backend is residence: an operational adapter name in
  signed declaration history would make a storage choice part of the vertex's
  absorbed identity.
- **`_residence_stripped` helper added to `test_document.py`.** The diff/apply battery
  asserted against `_edit(b, store=None)` at 9 sites — residence stripping spelled
  inline. Residence is now two fields, and an assertion clearing only one would pass
  while proving less, so the concept is named once instead of spelled nine times.
  Parallel to the existing `_ingress_stripped`.

## Commit (b) — the declaration threading

`engine/declaration.py`, `engine/program.py`, `engine/tests/test_declaration_resolver.py`.

**Counts: engine 1989 → 1993 (+4)**, all in a new `TestBackendResidence`: the backend
never enters store payloads; it survives resolution from the store; it survives
ingress re-attachment; a bare store resolves with no backend.

### The hazard was wider than the brief's two call sites

SD-5 names `documents_to_vertex`'s two callers. There are **three** places a residence
field can be dropped, because `ast.py`'s `_frozen` decorator defeats
`dataclasses.replace`: every rebuild-from-an-existing-AST reconstructs `VertexFile`
through the constructor with a hand-written field list, and a field it does not name is
a field it drops.

- `engine/declaration.py:892` — `_reattach_ingress`. It runs **on the freshly-threaded
  result**, so it would have silently undone the threading one line later.
- `engine/program.py:254` — source-param substitution. Carries the locator, so it must
  carry the designation; carrying the location but not the adapter is the same silent
  degradation one layer down.
- `engine/builder.py:192` — **deliberately not carried.** It constructs a fresh AST from
  builder state with no source AST to carry from, and the builder has no backend setter.
  Adding one would be new surface beyond this WP. Default `None` is correct there.

Emitted as `finding:slice2-wp4-vertexfile-rebuild-sites-drop-unnamed-fields` (high),
including the generalization for slice 5: the durable fix is a constructor-completeness
ratchet over the rebuild sites, not per-field vigilance.

## Commit (c) — registry, Rule 18 join, parity probe

`engine/arrival_registry.py` (new), `engine/tests/test_arrival_registry.py` (new),
`tests/architecture/test_rule_18_arrival_vocabulary_denylist.py`.

**Counts: engine 1993 → 2016 (+23)** — the registry suite. Architecture stays at 99:
WP1's ratchet already existed, it just went from red to green.

### The designed red, captured before registering

With `arrival_registry.py` present and unregistered, WP1's completeness ratchet fired
and named the file — the failure the brief says is by design:

```
E       AssertionError: Arrival-surface modules not held to the glossary:
E           libs/engine/src/engine/arrival_registry.py
E         Add each to _SCAN_TARGETS, or to _NOT_SCANNED with a reason.
FAILED tests/architecture/..::test_every_arrival_named_engine_module_is_scanned
```

Registered in the same commit, so no commit lands red.

### Design choices

- **`descriptor_for` is pure and `open` is where `UnknownBackend` lives.** Naming a
  descriptor and opening one are different questions: a vertex may declare a backend
  this host has no adapter for, and describing it must still work. Only the registry
  knows what is installed, so only the registry can refuse. Pinned by a test that
  describes a `backend="postgres"` vertex successfully.
- **A fourth arm the design's three do not name: no store clause at all.** 7 of the 11
  tracked `.vertex` files are that shape (aggregates and loops-only vertices), so the
  probe hit it immediately. Answered `None`, same as jsonl/sqlite, via an early guard
  before any path arithmetic. Emitted as
  `finding:slice2-wp4-descriptor-for-fourth-arm-storeless-vertex` (low) because it
  widens a ruled enumeration.
- **`StoreDescriptor.location` is stringified**, per WP1's deliberate `str` typing; the
  probe normalizes through `Path` when comparing artifacts.
- **No global registry, no registration at import.**
  `BackendRegistry.with_builtin_backends()` returns a fresh instance. A process-wide
  singleton is a decision with no forcing consumer yet — slice 5's rewiring is where one
  would earn its keep. Re-registering a name refuses, so import order can never decide
  which adapter answers to `"file"`.
- **Adapters imported lazily inside the opener**, pinned by a subprocess test asserting
  that `import engine.arrival_registry` pulls in neither `sqlite3` nor `engine.arrival`.
- **The opener's declared return type is the surface it is FOR, not the surface it
  reaches today.** `FileLedger` does not satisfy `ArrivalLedger` yet — `replicate` and
  `export` are WP2's, deliberately absent rather than stubbed, and WP1's own test pins
  that absence. The registry test asserts the ops actually offered and records the gap.
  No static type checker runs over `engine` in CI (`ruff` covers `libs/custody` and
  `libs/sign` only), so the annotation is documentation.

### Parity probe (§D.4 exit 3)

Enumerates via `git ls-files`, not a filesystem walk: a walk sweeps in `.loops/`, which
is gitignored and machine-local, and the probe's result would depend on whose machine
ran it.

**Scoped, not missed:** no tracked `.vertex` is arrival-canonical, so the repo sweep
exercises the jsonl, sqlite and no-store arms only. The arrival arms are covered by
minted `.arrival` fixtures — both the explicit and the transitional arm — which is the
only place they can be covered until a real vertex declares one. Stated in the test
docstring so the gate re-running it is not surprised.

The fixture probe asserts at two levels: the descriptor **names** the same log
`open_canonical_store` opens (`Path(descriptor.location) == legacy.log_path`), and the
ledger the registry hands back is **over** that artifact (`ledger.head().ordinal`
matches the log's head; the query's watermark lineage matches the log's).

## Mutation demonstrations

Three run, all restored, `git diff` clean after each.

1. **Unknown-property refusal reverted** → `TestStoreBackend::test_unknown_property_refused`
   fails with `Failed: DID NOT RAISE ParseError`. Restored, diff clean.
2. **Threading dropped from `documents_to_vertex`** → 4 failures:
   `test_roundtrip_via_documents[backend_declared]`,
   `test_roundtrip_via_genesis[backend_declared]`,
   `test_backend_survives_the_document_round_trip`,
   `test_order_preserved_after_shuffle[backend_declared]`. Restored, diff clean.
3. **`_reattach_ingress` carry dropped, threading left intact** (extra demo, not in the
   brief) → `3 passed, 1 failed`: only
   `TestBackendResidence::test_backend_survives_ingress_reattachment` catches it. This
   is the evidence that the third rebuild site is a real, separately-testable hazard —
   a WP that tested threading without an ingress-shaped vertex would have shipped the
   bug green. Restored, diff clean.

## Oracle status

| # | Criterion | Status |
|---|---|---|
| 1 | Parser: both forms accepted; unknown prop / child block / empty backend refused; mutation demo | green — 7 tests, demo 1 |
| 2 | Round-trip with the arm intact; backend absent from genesis blob; mutation demo | green — demo 2 |
| 3 | Parity probe over every repo `.vertex` | green — plus minted arrival fixtures |
| 4 | `residence.py` diff-empty; `test_residence.py` green unmodified | green — both 0-line diffs vs `0d38c969`, 23 passed |
| 5 | Rule 18 green; lang + engine suites green; counts reconciled | green — 99 / 670 / 2016+1skip |
| 6 | `git ls-files` clean on all changes | verified below |

## Full-suite check

`./dev test` — **2530 passed, 1 xfailed. "All test suites passed."** (every workspace
package, including `store` and `apps`, whose consumers of `documents_to_vertex` and the
`.vertex` grammar are the ones an additive change could still break.)

## Deviations

**None from the brief's scope.** `residence.py` is diff-empty, no consumer was rewired,
no `role`/`lineage` properties were parsed, no child-block grammar was added, and
nothing in a production path calls the registry.

Three things were reported rather than absorbed silently, each with a finding fact:

1. `finding:slice2-wp4-vertexfile-rebuild-sites-drop-unnamed-fields` (high) — the
   third rebuild site, and the ratchet generalization for slice 5.
2. `finding:slice2-wp4-registry-open-needs-a-projection` (medium) — `open` refuses a
   minted log with no projection beside it. **Left unresolved on purpose**: whether an
   absent projection may be materialized on the way in is exactly the boundary the §E
   F2 addendum puts to Kyle at this gate. Deciding it here would be WP4 ruling on a
   question it was not given, so the adapter's behavior passes through unchanged and a
   test records what it is.
3. `finding:slice2-wp4-descriptor-for-fourth-arm-storeless-vertex` (low) — the
   store-less arm the design's three do not enumerate.

Scope discipline held where it was tempting not to: the brief names exactly three
refusals, so no extra-positional-args refusal and no `BackendDecl.__post_init__`
validation were added. Empty `store "…" { }` is accepted (CKDL normalizes an empty
block to no children — the same known limitation already documented for `preview`);
noted at the refusal site rather than worked around.

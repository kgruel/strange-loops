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

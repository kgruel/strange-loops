# Slice 2 / WP5 impl brief — contract-text execution, doc pass, residue sweep

Arc: `design:arrival-break-implementation`. Slice contract:
`design:arrival-break-slice2-backend-contract` @ `01M177MHWHD5HM574VSTDE17X8` (§D.5).
Sitting rulings you EXECUTE: `decision:design/arrival-slice2-contract-text` @
`01M17M3RJJGC79KXH776Z4DQBR` — read it in full; it is binding. Wave branch:
`slice/arrival-backend-contract` @ e7513164 (all four WPs integrated, fully green).
Deviations are reportable (finding fact + report), never silent.

## Scope

### A. Ruled code changes (small, exact)

1. **`head_at` joins the contract** (ruling 3): one read-side Protocol method on
   `ArrivalLedger` in `arrival_contract.py` (coordinate/watermark → verified `Head`) —
   the adapter method already exists on `FileLedger`; align its signature if needed.
   Update `RATIFIED_LEDGER_OPS` in `test_arrival_contract.py` to the TEN-row literal
   (the exact-equality surface test must pass both directions with ten). If `head_at`
   is ledger-read rather than mutation, it does NOT join `LEDGER_MUTATIONS` — state
   the classification in the report.
2. **Typed `NotSupported`** (ruling 2): a `ContractRefusal` subclass in
   `arrival_contract.py`; the two WP1 sites raising `NotImplementedError` (pre-signed
   draft refusal, `Incremental` verify scope) re-raise it. Update any tests pinning
   `NotImplementedError`.

### B. Ruled doc changes (backend-contract.html)

3. **F2 callout** (ruling 1): the §06 `doc-callout is-security` exactly as drafted in
   `slice2-design-proposal.md` §E (the carve-out sentence included). Insert after the
   verification-levels discussion, matching the suite's existing callout style and
   inline-fact-ref conventions; ref the ruling fact.
4. **Refusal-root sentence** (ruling 2): §04-adjacent — the text-named conditions are
   typed under one refusal root; deliberate absence is typed `NotSupported`; all other
   failures are backend-specific by design.
5. **`head_at` row** (ruling 3): the §03 op table gains the tenth row; §07 gains the
   sentence connecting `projected_through` verification to it.
6. **§08 resumable-import debt marker** (ruling 5): "resumable import is required for
   conforming limited backends; the reference file backend does not yet implement it."
7. **§08 import stays off the table** (ruling 4): no row; if §08's prose reads as if
   the op table carries it, tighten the prose.

### C. Doc pass + residue sweep (proposal §D.5 + accumulated deferrals)

8. `backend-contract.html` status/conformance touch-ups for what slice 2 actually
   built (replicate vectors exist now; CAS is full-head per F1 — check the conformance
   §12 text against reality).
9. **WP4-F1**: `descriptor_for` docstring clause — its no-adapter-import claim holds at
   import time, not call time (residence.py's pre-existing `engine.arrival` coupling).
10. **CLAUDE.md sweep** (dissolution practice — same change, not follow-up):
    `libs/engine/CLAUDE.md` store table (admission.py now holds the admission op +
    fact commitment; the new arrival_contract/registry/file_backend modules exist);
    `libs/store/CLAUDE.md` where the admission move changed the described shape.
11. Sweep any doc claim slice 2 did not build. Check `index.html` / `protocol.html` /
    `witness-protocol.html` for statements the ten-op table or the F2 callout
    contradict.

## Non-goals

No consumer rewiring (SD-7 stands). No new ops beyond the ruled tenth. No resumable
importer (debt marker only). No KDL grammar changes. No `_canonical_bytes`
consolidation (slice 5). Nothing in `residence.py`.

## Oracle (the gate re-runs from scratch)

1. Full integrated suite green: engine (2062+1s baseline, plus your test updates —
   account for every delta), store 180, lang 671, architecture 99, apps 2530+1xf.
2. Surface-test mutation demos: (a) drop `head_at` from the Protocol → ten-row equality
   fails right-side; (b) add an eleventh op → fails left-side. (c) `NotSupported`: the
   two sites raise it and it is caught by `except ContractRefusal` — pin that with a
   test; revert one site to `NotImplementedError` → that test fails.
3. Docs: all five ruled texts present and faithful to the ruling fact (the gate diffs
   your HTML against the ruling's language); all five arrival HTML files parse with
   balanced tags; no doc claim slice 2 did not build.
4. `git ls-files` clean on every changed file.

## Mechanics

- Worktree: `git -C /Users/kaygee/Code/loops worktree add ~/Code/loops-s2wp5 slice/arrival-backend-contract`
  — work DIRECTLY on the wave branch (WPs 2-4 are merged; you are the only writer on
  it now). Step 0: verify HEAD is e7513164 or later.
- Report AS YOU GO: `docs/scratch/arrival-break/slice2-wp5-report.md` on the branch.
  Loops emissions from MAIN checkout cwd, payload
  `agent=s2wp5-impl slice=2 wp=5 role=implementer`; facts only; never stage `.loops/`.
- Commits conventional, trailer:
  `Claude-Session: https://claude.ai/code/session_01JpCUT3bF3dukDk5xjDejRM`
- Finish: SendMessage to parent — tip, files, counts with deltas, mutation results,
  deviations.

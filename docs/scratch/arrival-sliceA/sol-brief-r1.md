# Sol review brief — arrival wave 1, round 1 (post cut A)

You are the cross-family adversarial reviewer for the arrival migration's wave-1
branch. Your model family did not write this code; your job is to find what the
author family characteristically misses. Findings cluster at cross-slice seams
and post-review fix commits — weight your attention there.

## 1. Anchor

- Repo: /Users/kaygee/Code/loops (you are in it)
- Branch: `feat/arrival-libs`, head `69d1aabd`, 29 commits off `main` (406cec31)
- Diff under review: `git diff main...feat/arrival-libs` — 25 files,
  +6283/−130. Everything in that diff is in scope. Slice 0 (the arrival log
  primitive, `libs/engine/src/engine/arrival.py` through commit 3b303d5d)
  converged through four internal review rounds; cut A (everything after) has
  had one independent gate pass (CLEAN) and zero cross-family review. Nothing
  is fenced off, but cut A and the slice-0↔cut-A seam are the expected
  finding zones.

## 2. The design contract (what the code must honor)

Ratified store facts (the store is `.loops/data/project.jsonl`; grep by id,
payload is a nested JSON string):

- `decision:design/arrival-slice0-record-grammar` @ 01M09GNGW7VTSKDPYMJ027HEPR —
  the record grammar. NON-NEGOTIABLE: fields v,lin,ord,prev,at,k,observer,
  origin,body,sig?,rh in order; rh = sha256(JCS(record-without-rh)); prev
  chains rh; sig covers CONTENT ONLY (k,at,observer,origin,body) — never the
  coordinate; torn tail truncates only under the append lock; corrupt interior
  always refuses; genesis at ordinal 0 and nowhere else, sig REQUIRED.
- `decision:design/arrival-sliceA-authority` @ 01M0B0Z14T9ATPRAJTKBBMCQQT —
  cut A. NON-NEGOTIABLE rulings (Kyle, 2026-08-18):
  - Adoption genesis body = {protocol, lineage, key} — founding public key
    self-signed at ordinal 0. Document set at ordinal ≥ 1, never in genesis.
  - Verifier rule VERBATIM: a key is valid at position N iff introduced at a
    position < N, OR N is the genesis position and the record is
    self-certifying. Self-certification legal at ordinal 0 and NOWHERE else.
  - EXCLUSIVITY: the arrival verifier resolves keys from (lineage, ordinal)
    coordinates ONLY; no libs code consults the .vertex for arrival keys. The
    apps-composed tick-chain verifier and the .vertex observers{} registry are
    UNTOUCHED this slice.
  - SEAM: S1 a live-store genesis never carries a containment claim; S2
    migration pins dissolve, never relocate; S3 cut A converts NOTHING — every
    ceremony change is fenced on the .arrival locator, .jsonl/sqlite ceremony
    paths byte-identical in behavior.
  - apps/ diff-empty vs main (gate law; verify it yourself).
  - The keyless-genesis question is DEFERRED to the sidecar slice — cut A code
    or comments must not foreclose or half-build it.
- Slice-0's carried lesson, now an obligation: READING A RECORD FORWARD AND
  ADOPTING ONE AS A PREMISE ARE DIFFERENT ACTS. Every path that adopts an
  on-disk record as an authority validates at the adoption site
  (`_authority_fault` or an equivalently stated check). The accepted O(n)
  residual stays at its stated width: adoption proves decode+rh, placement,
  lineage match — deliberately NOT chain-to-genesis nor ordinal=physical-
  position. Verify no O(1) path silently narrows it (no hidden whole-prefix
  walks) and no new adoption site skips it.
- Caches: keyed on the validated input's exact bytes only. A path/inode/mtime
  key is a known-rejected trap with its own test.

## 3. Arbiter-accepted deviations — attack them

Six implementer deviations from the ratified design doc, all arbiter-accepted.
A deviation is where a design argument was overridden by implementation
evidence; verify the evidence and the blast radius:

- D1 `is_jsonl_canonical` kept as an unexported shim (design said DELETE)
  because apps/loops/commands/store.py:142 lazy-imports it before its mode
  check and apps/ is frozen. One Rule 18 allowlist entry + tripwire test.
- D2 second Rule 18 allowlist entry: arrival_store's refusing `def reanchor`
  override (the legacy name IS the refusal surface).
- D3 genesis crypto self-certification lives in `verify_authorship`'s first
  act, not `_placement_fault` (kept pure). Doubly-enforced; the impl report
  carries an equivalent-mutant analysis the gate empirically confirmed.
- D4 `arrival_store.py` joined Rule 18 `_SCAN_TARGETS` beyond the ruled two.
- D5 **the verifier binds keys to observers** — additive semantics beyond the
  ruled positional clause (a key introduced for observer X refuses to verify
  observer Y's records). This is instantiation beyond the ruling — the classic
  place holes hide. Probe it hard: rotation, re-introduction of the same key
  for a second observer, an introduction record whose body observer disagrees
  with its envelope observer, genesis-key impersonation.
- D6 arrival open-time out-of-band detection narrower than jsonl's (counts
  custody dissolved with the ratified resume mark); the arrival agreement
  audit is cut B's. Verify the docstring states it and nothing pretends
  otherwise.

## 4. Unverified fixes — re-verify these claims empirically

Every fix commit applied after its last independent review, newest first:

| commit | claim | independent verification so far |
|---|---|---|
| bba86e70 | CLAUDE.md residence section teaches shipped API | arbiter eyeball only |
| 9ec762fb | test_arrival_store.py pyright 7→0, meta_int/narrowing only, no behavior change | arbiter pyright re-run only |
| 850e679d | reconcile→append race: gap detected by the append's own coordinate, rollback+catch-up; `append_marked(following=)` CAS refuses before any byte | gate mutation-verified both arms |

r1's two commits (bba86e70, 9ec762fb) have had NO independent review — you are
their first. Verify 9ec762fb changed no test SEMANTICS (a type-narrowing that
weakens an assertion is a real finding class).

## 5. Known non-findings (don't re-report)

- Rule 17 fails in the arbiter's main checkout only: pre-existing, filed as
  `finding:rule17-scans-untracked-docs` (ratchet globs gitignored local docs).
- The ceremony crash window between log fsync and sqlite COMMIT parks a store
  on AmbiguousGenesis until cut B's restamp verb — disclosed, accepted, cut
  B's by ruling.
- Gate findings N2 (test_jsonl_ceremonies mechanical rename), N4 (probe mutant
  count), N5 (slice-0 minimal-body test replaced by ratified pins) —
  dispositioned informational.

## 6. Verdict format

Produce:
1. A findings list — each: file:line, severity (BLOCKING / behavior /
   test-strength / residue / docs), the failure scenario, and the empirical
   evidence (command you ran, output). No finding without a concrete failure
   scenario or a demonstrated gap.
2. A verdict table for §4's fix commits: PASS/FAIL each, with evidence.
3. A verdict line for each §3 deviation: UPHELD / OVERTURNED (with evidence).
4. Overall: CONVERGED (zero new findings) or NOT CONVERGED.

You have workspace-write: run the suites, write scratch probes, mutate and
restore. Do not commit. Suites: `uv run pytest libs/engine/tests` (1678+1s),
`uv run pytest tests/architecture` (98, Rule 17 fails pre-existing per §5),
sdk 313, store 131, apps 2525.

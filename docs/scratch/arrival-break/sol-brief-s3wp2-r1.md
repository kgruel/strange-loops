# Sol review brief — arrival-break slice 3 / WP2 (comparison vectors), round 1 (per-WP, LOW)

You are the cross-family reviewer for slice-3 WP2 — the comparison conformance family.
These vectors outlive this repo (a Go implementer builds against them with no access
to the Python module), so your review target is the FAMILY AS A CONTRACT: does it pin
the ratified state machine and the fought-over rulings, and nothing repo-specific?
You review and report — no fixes, no commits.

## 1. Anchor

- Repo checkout: this working directory (a git worktree of /Users/kaygee/Code/loops).
- Branch: `slice3/wp2-vectors`, tip `9735ce3f` (3 commits over WP1's `9ed893fe`).
- Diff spec: `git diff 9ed893fe...9735ce3f`. Generator + 26 vectors + consumer +
  SCHEMA.md §11 + report.
- Suites: engine per-package; architecture SEPARATELY (cross-suite pollution).

## 2. Design contract

`design:arrival-break-slice3-witness-minimum` §C/§E-WP2 + the finding folds (the
rulings are NEWER than the design doc): reset-INCLUSIVE epochs; incomplete reads yield
an unignorable lower bound (rollback-only); headerless-with-entries = bound;
content-present-nothing-readable declines everything incl. re-mint; three-way header
classification. Vectors pin outcome STRINGS from the ratified seven (∪ null for
declining reads — deliberately NOT an eighth string); `expected.read` names what the
read reached; `skipped` is a count; `sound_answer` scoped {"rollback", null} and
lineage-replaced-against-a-bound is deliberately INEXPRESSIBLE (arbiter deferral —
finding:s3wp2-lineage-replaced-against-bound).

## 3. Unverified fixes

None — no post-gate fixes. Gate PASSed at the reviewed tip: all four mutation demos
re-run with exact counts, both inventory directions, schema defeat-tests (an
outcome:"declined" vector fails twice; the SOUND_ANSWERS frozenset trips on
lineage-replaced), fixture-byte reads for all five fold behaviors, purity hostile-run.
Its two NB findings are dispositioned (sound_answer enforcement relayed to WP3;
purity-ratchet aliasing dismissed on scope-the-claim).

## 4. Seeded review targets — the cross-family angle only you can take

- **Foreign-implementer ambiguity**: read SCHEMA.md §11 AS the Go implementer — is
  any field's semantics underdetermined without reading the Python module? (e.g. what
  exactly must an implementation DO for `read: "bounded"` — is the rollback-only rule
  stated in the schema or only in this repo's rulings? If a conforming implementation
  could answer `advanced` from a bound and still pass every vector, say so — that is
  the gap between what the family PINS and what the contract MEANS.)
- **Coverage holes in the state machine**: the seven outcomes × the read states —
  enumerate the meaningful combinations and check each is either covered by a vector
  or provably inexpressible. The gate verified the named behaviors; you hunt the
  UNNAMED cells.
- **Fixture realism**: the journal-form fixtures were built through the real
  append_entry — are any damage splices producing byte patterns a real crash/editor
  could not produce (i.e. vectors pinning implausible states)?
- **The heads/journal split boundary**: is there any ruling that ONLY the journal form
  encodes but that a heads-form-only implementation would silently miss — and does
  SCHEMA.md tell the implementer both forms are mandatory?

## 5. Verdict format

Per §2 behavior: PASS/FAIL + evidence. New findings: `S3WP2-L-<n>`, file:line,
severity (BLOCKING/NON-BLOCKING), concrete failure scenario, evidence. Then one line:
**CONVERGED** or **NOT CONVERGED** (with the blocking list).

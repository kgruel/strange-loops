# 0.9.0 consumer-evidence wave — arbiter fork rulings

loops-claude, 2026-07-18. Build order (sequencer-confirmed): **S1 → S2 → S3 → S6 → S4 → S5**.
Every implementation agent reads this before starting. Rulings are binding for this wave;
re-open only with a concrete blocker, and route the re-open through the orchestrator.

## S1 — typed-address

**F1: `Edge.address` stays `str` (STR-STAYS).** `Address(kind, key)` is the value-object at
every parse/build/match boundary; the stored/rendered field remains the canonical
`kind:key` string. Rationale: the defect class lives at the boundaries, not in the field
type — typing the field ripples through lenses/goldens/JSON for zero defect-fixing benefit.
The contract (one shared interpretation) is the fix; the silhouette (field type) is not.
Consequence for S3: its single membership helper parses the canonical string via
`Address.parse` — communicated there.

**F2: legacy-slash parse branch is PRESERVED indefinitely at read time.** 493 live
`kind/key` refs in the project store keep matching. No store rewrite in 0.9.0 — rewriting
refs at rest is the ulid-wedge question again and the standing position is
leave-as-historical-fact. If a migration ceremony is ever wanted, it is its own explicit
arc, not a rider.

**F3 (new site, live specimen from this session):** `sl cite` POSITIONAL refs and
`sl emit ref=` disagree on the same address — `cite thread:090-consumer-evidence-wave`
stored an unresolved pin while `emit ref=` resolves it. Add the cite-verb positional path
to the site enumeration, converge it on the same Address resolution, and pin with a test
(cite and emit must resolve identically for identical input). This is in-scope for S1.

## S2 — FTS read-purity

**F1: `Window.stale` is a NEW distinct field**; `unindexed` semantics unchanged.
Never-declared and declared-but-stale are different claims; Window's convention is
one-field-per-distinct-signal (`limited_by`, `granularity`, `unindexed` are already
separate axes). Additive `--json` field = safe for consumers. S5 inherits this Window
shape and must not re-open it.

**F2: friction:fts-match-limit-100-silent-cap is IN scope, disclosure-form only.** S2
rewrites exactly this region: when FTS truncates at the limit, record it in Window
(no-silent-caps) — keep the default limit itself unchanged. No limit redesign.

**F3: byte-identity tests** — prefer asserting `facts_fts`/`fts_state` table absence +
row counts over raw file bytes if WAL/checkpoint noise appears (brief's own risk note is
endorsed).

## S3 — graph build-2

**F1: sub-scope compute stands.** Inbound counts/chains/tiers compute over the in-scope
sub-graph (matches shipped `--kind` semantics); the full-vertex node set is loaded ONLY
for (e) classification. Global-compute would silently change `←N` meaning under filters.

**F2: orphan taxonomy — three named buckets, no fourth.** Node-classification carries
`keyless` (source not addressable — the existing unsourced logic); edge-resolution
partition carries `dangling` (target does not resolve in the full vertex) vs
`filter_excluded` (resolves, but outside current scope). Returned dict exposes all three
counts/lists distinctly. Do not invent an outbound-keyless bucket.

**F3: `--edge` without `--lens graph` REFUSES** with a teaching message pointing at
`--lens graph` (184dfce idiom). Silent no-op is the defect class this wave exists to kill.

**F4: shell completion glue for `--edge` is OUT of 0.9.0 scope** (completion arc closed
with its own deferred list; don't reopen it as a rider).

## S6 — honest seal provenance (build position: 4th)

**F1: substrate-first, data-only for default TTY reads.** `render_context` gains an
unconditional `cut` key (present on every read, including plain `sl read`), and `--json`
carries it; the BUILT-IN fold lens does NOT grow a new default banner line this wave.
Grounding from research: the built-in lens is already honest (renders provenance only
when handed one); the lying "Live unsealed fold" banner is in the EXTERNAL homelab-audit
consumer lens, which defaults `projection=None`. Loops's defect is substrate absence, and
that is what ships. Whether plain `sl read` should surface a default cut line is a
Kyle-level UX question — queued for the wave-review discussion, not decided silently here.
Consequence: NO fold-golden churn from S6.

**F2: consumer notification is part of DONE** for this slice: the N=2 consumers
(homelab-audit, siftd) get a store-fact notice that honest cut provenance now exists in
render_context/`--json`, so their lenses can drop the None→"Live unsealed fold" guess.
(Orchestrator emits; implementer provides the one-paragraph payload.)

**F3: test home: `apps/loops/tests/test_fold_cut_provenance.py`** (new file), not an
extension of the cursor tests.

**F4: banner-honesty within THIS repo:** wherever loops-side code renders a
provenance-bearing statement, absence must render as "unavailable", never as a positive
claim. Audit the built-in lens paths touched; do not add new banner lines (F1).

## S4 — canonical review projection (build position: 5th)

**F1: decl-generation = content-hash fingerprint (default) + decl-head event id where it
exists.** The fingerprint is labeled a REVIEW fingerprint — documented as distinct from
SPEC §10.2 JCS canonical bytes, no interchange claim. Adopted stores additionally surface
the decl-head ULID. This is a new disclosed contract field: name it and document it in
the projection header.

**F2: head-cursor disclosure ships in the `--review` header and `--json` cursor field
ONLY.** No always-on TTY cursor line on default reads (pairs with S6-F1; fold goldens do
not move for disclosure this wave). Always-on TTY head disclosure is queued for the same
Kyle-level UX discussion.

**F3: head-resolution is SHARED with S6.** S6 lands `resolve_witness_position(store,
'head')` plumbing first; S4 MUST reuse/factor with S6's resolution — a second independent
head-resolve path in `fold.py::run()` is a refusable review finding.

**F4: scope stop-line confirmed:** the projection serves REVIEW (diffable snapshot).
Witness order is rebuild/chain authority; (ts,id) is fold-replay authority; the
projection is neither. Anything approaching SPEC §10 dump territory (JCS bytes,
round-trip, residence modes) is out — gated on GlobalReceiptPosition with loops-go.

## S5 — declarative entity lifecycle (build position: 6th)

**F1: whitelist syntax, fail-open on missing.** Clause declares the ACTIVE set
(domain-neutral, per grammar-domain-neutrality). A fact whose status value is NOT in the
active set is omitted from the default fold view (Window.limited_by="status" + hidden
count + `--all` defeat + explicit `status=` predicate auto-disables). A fact LACKING the
status field is SHOWN — a fact making no lifecycle claim is not claiming inactivity;
absence of evidence is not evidence of inactivity (same honesty axiom as S6). The
validate surface WARNS on missing-status facts under lifecycle-declared kinds, so the
gap is visible rather than silently resolved either way.

**F2: validate scope = minimal targeted scan.** Active-targets-inactive edge-scan bolts
onto `loops validate`; the general folded-state constraint surface stays with
design:architecture/payload-constraints-in-declarations as its own future arc. This scan
is that design's first tenant precedent, not its implementation.

**F3: DECLARATION_PROTOCOL_VERSION does NOT bump.** Additive field under §9.2
forward-compat. **Cross-repo rule: S5 does NOT edit `/Users/kaygee/Code/loops-go/SPEC.md`**
— the spec-delta is documented loops-side (docs note + store fact) and queued onto the
existing loops-go protocol-package coordination batch (GlobalReceiptPosition + decl
receipt-group id + vectors). No writes outside this repo from any wave agent.

**F4: source-site correction:** S5's code lands in `surface.py::budget` +
`cli/dispatch.py::_project_surface` + lang loader + engine FoldSection build — NOT
`commands/fetch.py`. Tests: `apps/loops/tests/test_lifecycle_hide.py` (new) + lang loader
tests. Acceptance = the REAL end-to-end deprecation walk (declare on a test vertex, walk
an entity terminal, observe omission + provenance + `--all` + salience retention +
validate warn).

**F5: status-aware-kind-budget disposition:** S5's landing re-emits
design:rendering/status-aware-kind-budget as `superseded` `superseded_by=`
the lifecycle design (it is the first tenant, not a sibling). Orchestrator emits at
slice close.

## Golden discipline (all slices)

Fold goldens move at most ONCE this wave (S5's footer, and only where a fixture declares
lifecycle). Graph goldens are S3-isolated. Every golden regeneration is hand-verified
line-by-line — never bulk `--update-goldens` over unread diffs.

## Shared discipline

- Sequential slices, one branch, one commit per slice (+ fix commits after sol review).
- After CLI changes: `uv tool install . -e`, smoke via installed `sl` (production path).
- Agents do NOT emit to any loops store; the orchestrator holds all emissions.
- Full package tests for touched packages green before a slice is declared done; the
  orchestrator runs the cross-package gate between slices.

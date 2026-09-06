# Descriptor completion — Fable adversarial review

Date: 2026-09-05  
Scope: descriptor declaration, resolution, registry enforcement, and related tests  
Reviewer: Claude Fable 5.1, static packet, tools disabled

## Invocation and evidence

The review ran with:

```text
claude -p --safe-mode --model 'claude-fable-5-1[1m]' \
  --no-session-persistence --tools '' --output-format json
```

The prompt contained the scoped diff, the backend-contract §01–04/§12 rulings,
the completion-worklist stage, the root ruling for transitional `role=None`, and
the pre-review validation. The exact packet and raw result are outside the repo:

- `/tmp/loops-arrival-review/descriptor-prompt.txt`
- `/tmp/loops-arrival-review/descriptor-result.json`
- `/tmp/loops-arrival-review/descriptor-stderr.txt`

Returned model metadata confirms `claude-fable-5-1` as the substantive model:
1,000,000-token context window, 2,334 thinking tokens, 67,700 output tokens,
106,641 cache-read input tokens, and 82,764 cache-creation input tokens. The
result also reports a 15-token `claude-haiku-4-5` routing/classification call.
Total duration was 890,689 ms. No web searches or tools were used.

## Initial verdict

`not ACCEPTED as-is`

Fable reported three majors, three minors, and one nit. Two majors and two
minors identified concrete contract or cleanup gaps and were fixed. One major
correctly names the still-unmigrated legacy-consumer boundary, but its proposed
fix belongs to completion stage 2 and was not pulled into this descriptor-only
stage.

## Findings and dispositions

1. **Major — Archive could reach head/read/scan/export. Fixed.**
   `_DescriptorLedger` now enforces the complete ratified operation table:
   Authority for mint/append; Authority or Replica for head, head_at, replicate,
   read, scan, and export; Archive additionally for verify; capabilities for all.
   A synthetic Archive-capable adapter test proves verify succeeds while the
   Authority/Replica operations refuse.

2. **Major — replication records without string `lin` reached the backend.
   Fixed.** Every record offered under a pinned descriptor must name a string
   lineage equal to the pin before delegation. Both a foreign lineage and a
   missing lineage are tested byte-for-byte unchanged at the target.

3. **Major — `VertexFile.store` remains Path-shaped for legacy consumers.
   Scoped, with remaining debt explicit.** This stage adds `store_location`, an
   exact residence field, and `descriptor_for` exclusively uses it for non-file
   adapters; DSNs/service URLs therefore reach the selected adapter unchanged.
   The old runtime consumers still use `VertexFile.store` and suffix resolution.
   Moving those consumers is explicitly completion stage 2 and was excluded by
   the task boundary (“do not edit SDK/runtime/query contract”). Until that cut,
   parsing a non-file descriptor does not itself make old runtime entry points a
   supported open path.

4. **Minor — broad exception catch around the pre-attestation genesis probe.
   Not changed.** The ratified contract has no backend-neutral absent-ledger
   refusal. Fable's suggested `NoLedger` type does not exist. Narrowing this
   catch would either hard-code the file adapter's `GenesisRefused` or invent a
   protocol refusal. The immediately following `AttestedLedger` observation has
   the same ruled broad-catch posture and carries the backend refusal in its
   `PreGenesis` report; a remembered location still refuses as lost.

5. **Minor — query cleanup omitted a closeable ledger half. Fixed.** A refused
   registry open now best-effort closes both halves without masking the primary
   refusal. The test asserts both close callbacks and an untouched journal.

6. **Minor — in-memory non-file AST could fall back to a lossy Path spelling.
   Fixed.** `descriptor_for` now refuses a non-file declaration lacking its
   opaque `store_location`; it never guesses from `str(Path(...))`.

7. **Nit — duplicate the `"file"` literal between lang and engine. Not changed.**
   Lang deliberately does not import engine. Adding a second public constant or
   a cross-layer import would not eliminate the duplicated wire spelling.

## Additional audit dispositions

- An export result's head is now checked against the descriptor pin.
- Explicit descriptor locations must be strings and must not be blank. Legacy
  bare-store coercion remains unchanged.
- Mint, append, and replication validate their caller-owned lineage inputs
  before delegation. They do not raise a fresh descriptor refusal after a
  backend returns a durable foreign result: that would prevent
  `AttestedLedger` from witnessing the committed transition and misreport it as
  precommit failure. A backend that violates its mint/CAS/replication lineage
  contract is conformance debt; the current neutral refusal vocabulary has no
  committed-descriptor-mismatch result.
- CKDL normalizes duplicate properties with last-property-wins before the loader
  receives a node. The architecture suite does not rule duplicate-property
  semantics, so this stage does not add a bespoke source lexer or invent a
  different KDL protocol.

## Post-fix validation

- Language: **721 passed**
- Registry + contract + head seam: **149 passed**
- Migration sidecar: **69 passed**
- Architecture: **101 passed**
- `ty check src/engine/arrival_registry.py`: passed
- `git diff --check`: passed

The complete engine suite had already passed immediately before review fixes:
**2,312 passed, 1 skipped**. Post-review changes were confined to registry
guards/cleanup and their focused tests; the 149-test registry/contract/seam set
was rerun after them.

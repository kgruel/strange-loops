# Arrival review remediation — September 6, 2026

User authorized remediation of the six behaviors reproduced in
`reviews/fable-followup-2026-09-06/primary-triage.md`. Sol owned literal prefix
lookup; Terra owned custody and its load/publication primitive; Luna owned
Arrival hydration/boundary consumption. Root owned export/recovery reporting,
integration judgment, regression follow-up, and the low-effort Fable reviews.

## Implemented behavior

- **Custody identity and selection.** Exact observer spellings are retained.
  Aliased directory components refuse before key creation, including parent
  directories without keys. Existing locator basenames must match their physical
  spelling for self identity. One resolver serves ensure, tick, fact and Arrival
  signing: sole flat/nested key retained, identical copies select flat, differing
  copies refuse. A differently spelled nested observer is distinct, not a self
  fallback. Exact self symlinks refuse instead of causing a competing flat mint.
- **Reserved local paths.** Directory-mapped components cannot occupy
  `ed25519.key` or `ed25519.pub`, including case variants; existing regular files
  in directory positions refuse clearly. Reserved self stems stay flat-only.
  This is local filesystem custody policy, not an event-protocol label restriction
  or a restriction on externally supplied signer capabilities.
- **Load and concurrent creation.** New `sign.ed25519.load` is read-only. Signer
  loads cannot regenerate deleted keys. Concurrent explicit creation publishes
  one complete private key exclusively; all callers load the winner and derive
  its convenience public file. No persistent lock or automatic migration.
- **Literal prefixes.** Exact visible IDs win; otherwise a literal UTF-8 byte
  predicate handles Unicode, `~`, `%`, `_`, `[` and NUL. Ambiguity and receipt
  coordinate pagination remain intact, without sentinel alphabets or patterns.
- **Local boundary evidence.** Arrival hydration/pending planning requires a
  nonempty origin matching the local vertex before a tick can reset loops,
  establish period state or consume a same-named boundary. Other ticks remain
  captured/query-visible. Existing event-time/receipt/precision rules remain.
- **Export evidence.** Source errors retain source classification; output errors
  carry publication state. A second close error adds a note without masking the
  primary failure. Partial output never publishes. Private staging, exclusive
  publication and post-link durability reporting are retained.
- **Recovery evidence.** `file_written` reports this invocation's publication.
  Already-published recovery returns False, recovered status, published phase,
  unchanged cache bytes/inode/mtime, no fabricated Commit or semantic changes.

## Review and validation

New regressions reproduce failures before the fixes and pass afterwards.
Root independently reproduced Fable's export cleanup-masking concern and the
empty-origin hydration question before fixing them. Custody covers actual APFS
cases, portable filesystem simulations, load-deletion races and concurrent mint.
All three low-effort reviews are complete; confirmed findings are corrected.
Raw Fable packets/results, hashes, primary triage and final suite
counts are in `reviews/remediation-2026-09-06/`. Reviews are static; native agents
and root supply execution evidence. Findings from the first two reviews were
addressed before the subsequent narrowed review.

## Remaining scope

The source-aware projection preservation/rebuild operation remains design only.
Larger Arrival completion work and earlier secondary findings remain separately
tracked. Legacy replay/evaluate semantics and legacy StoreReader prefix lookup
remain transitional; these changes target the Arrival adapter/runtime.

A preexisting namespace ambiguity remains when a vertex boundary and a
boundary-bearing loop share the same name within one origin. The tick wire
model does not distinguish their roles. That needs a namespace/refusal decision;
this pass corrects the reproduced cross-origin case without changing wire format.

Names must round-trip with exact spelling in their filesystem. If a filesystem
rewrites a Unicode spelling, the current directory layout refuses that label;
portable support requires encoded key paths or persisted identity mapping. This
constraint does not change event-protocol observer identity.

Atomic key creation requires hard-link support. It establishes exclusive
process-concurrent publication, not a new power-loss recovery protocol.
Caller-configured key roots and hostile concurrent directory renames are outside
these identity-collision checks.

Changes remain uncommitted in `arrival/finish`. Main checkout and live stores
are untouched; no history was rewritten or witness floor lowered.

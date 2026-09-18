# Explicit fresh runtime epoch at adoption

## Decision and scope

The real loops-store rehearsal (`2a75980c`) preserved 121 old ticks, including
owned vertex-period ticks before the new declaration anchor. C6 correctly
refuses consuming those ticks without proven declaration continuity. The user
selected “Start a new boundary epoch at adoption; define its initial state.”
This design adds an explicit opt-in execution cutover. It does not invent
historical declarations or reinterpret old ticks as proven boundary events.

## Initial state

Let S be the reviewed migrated head and A the own declaration anchor appended
at S+1. For a fresh epoch:

- Each runtime fold starts at its declared identity/initial value. No old fact
  seeds its mutable execution state. Static declarations and pinned source
  configuration still apply.
- Boundary counters start at zero; one-shot boundaries are not exhausted;
  there are no pending old boundaries, old loop resets, or old vertex-period
  timestamps. The normal first post-A event starts period context.
- Runtime replay consumes only facts/ticks whose physical Arrival ordinal is
  strictly greater than A. A backdated post-A event remains in this epoch;
  wall-clock/event timestamps never select the execution floor.
- Post-A declarations and ticks retain all existing C6 continuity/refusal
  checks. A fresh marker is not permission to ignore later corruption, name
  reuse, unknown generated roles, or declaration discontinuities.

## Execution state versus custody evidence

Filtering applies to runtime hydration, count/reset/period interpretation,
source cadence and pending work, and the public current `read_state` view.
Aggregate current state applies each member's own floor independently.

Filtering does **not** apply to source preservation, raw fact/tick queries,
summary counts, Full verification, exact export, or global ID/idempotency checks.
An old ID cannot be reused merely because it predates the epoch.

The physical tick chain also remains global: `prev_hash`, fact cursors, and
window hashes continue the custody chain across A, using all required historical
rows. An old tick can remain the cryptographic predecessor without becoming
a runtime reset/count/period edge. Resetting that chain would be a different
wire/audit change and is excluded.

## Signed representation and compatibility

SDK adoption receives `runtime_epoch="strict" | "fresh"`, default `strict`.
Strict emits the current protocol-1 genesis without an epoch marker and keeps
the current behavior. Initialization continues to emit protocol 1.

Fresh emits declaration protocol 2 with the exact payload marker
`"runtime_epoch": "fresh-after-anchor-v1"` alongside the reviewed documents.
The existing FACT and ARRIVAL signatures cover this payload. Protocol 2 is
required so protocol-1 readers refuse instead of silently replaying old state.
The physical Arrival wire grammar is unchanged.

Central payload validation accepts the supported combinations only: v1 has no
epoch marker; v2 requires the exact marker. Unsupported/malformed combinations
refuse. No declaration edit can invent or move this immutable genesis floor.
The own store-local anchor must match physical lineage, fact identity/kind and
its actual receipt ordinal; foreign merged genesis facts cannot select a floor.
No mutable locator flag or free-standing projection metadata grants this mode.
At runtime the projected anchor is compared with the exact physical anchor from
the attested custody read, including its payload and signatures; both inventing
and stripping the marker in the projection refuse. This is not a new claim to
independently reverify every historical signature on every read. The supported
SDK prepare/recovery paths independently verify both domains before publishing
the anchor; deliberately false low-level injected verifiers/raw ledger writes
remain the existing trusted low-level API boundary.

Recovery takes no caller-supplied epoch override. It reads the reserved mode
from the intent field, cross-checks it against the exact draft payload,
reconstructs the same canonical payload, and independently verifies both
signature domains. Marker tampering cannot
change the epoch while retaining authentic signatures. Results expose the mode
and anchor; `head` and Commit(S,A) retain their existing meanings.

## Rehearsal and acceptance

Keep the strict rehearsal and its refusal evidence unchanged. Run a fresh
rehearsal on a separate copied descriptor and output, using the same audited
prepared source. Preserve the original and prepared source hashes.

Required coverage:

1. Default strict mode still refuses consumed pre-genesis owned ticks.
2. Fresh mode starts empty/declared state at A while historical query counts
   and exact export retain all old rows and signatures.
3. Ordinary signed writes and a new boundary tick succeed; current state sees
   post-A facts only, including backdated arrivals.
4. Tick-chain audit remains valid across the execution epoch; global duplicate
   detection still sees pre-A IDs.
5. Post-A reset/count/period behavior, declaration continuity, source cadence,
   and aggregate state follow the same floor without weakening later checks.
6. Malformed/foreign epoch evidence refuses; protocol-1 readers reject the
   fresh payload; default initialization and old anchors are unchanged.
7. Both interruption boundaries recover the same signed epoch and exact anchor
   without credentials, including refusal of self-consistent tampered markers.
8. Rerun the real loops copy through reads, writes, exact export and recovery.

Sol owns engine/lang implementation; Terra owns SDK/state/rehearsal integration;
Luna provides adversarial review; root owns integration acceptance and evidence.

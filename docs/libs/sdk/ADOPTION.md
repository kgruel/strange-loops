# Adopt a migrated Arrival declaration

`sdk.adopt_arrival` appends the declaration anchor that makes a migrated
Arrival history usable by ordinary SDK reads and writes. It preserves the
migration prefix and uses the existing physical lineage. Fresh stores use
`init_vertex`; stores with an adopted declaration use `edit_declaration`.

The caller supplies two distinct snapshots:

- `reviewed_text` and its `reviewed_sha256`: exact declaration bytes selected
  for adoption, such as the copied legacy vertex used for migration.
- `declaration_text`: the current published vertex, naming an explicit backend,
  physical lineage, and authority role.

Their declaration documents must agree apart from residence. This first
operation cannot introduce or replace observer keys, or adopt a changed
declaration as an incidental part of migration. It checks the selected head,
registry-forming signatures, declaration identities and captured observer keys
before signing the new anchor.
It independently verifies the resulting FACT and ARRIVAL signatures against
the selected mapped binding's public key; a provider-local verifier cannot
replace that check.
It also checks that the selected backend provides projection catch-up before
resolving signing credentials; the preflight does not advance the projection.

```python
from sdk import adopt_arrival

# Keep these snapshots and the report verification receipt from the offline
# migration workflow. Verify its report at selected_head BEFORE adoption.
result = adopt_arrival(
    published_vertex,
    selected_head=migration.head,
    reviewed_text=reviewed_text,
    reviewed_sha256=reviewed_sha256,
    declaration_text=published_vertex.read_text(encoding="utf-8"),
    observer="alice",
    credentials=mapped_provider,
)
receipt = result.as_dict()
```

The mapped binding must already exist and match the observer's captured key
history. Adoption resolves distinct FACT and ARRIVAL authorship requests;
neither lookup creates keys nor falls back to legacy credentials. The result
retains the adoption commit, projection outcome and public binding evidence.
Migration report verification remains the offline caller's responsibility;
the report's live-head comparison no longer applies after adoption advances
the history.

Before appending, the operation durably reserves the exact signed draft in
`<vertex>.arrival-adopt.intent`. If interrupted, retain the intent and the
typed error's commit/head evidence, then reconcile explicitly:

```python
from sdk import recover_arrival_adoption

recovered = recover_arrival_adoption(intent_path)
```

A stale apply may leave this intent reserved; use its `intent_path` for explicit
recovery before attempting a fresh adoption. Maintenance capability is checked
again before apply or recovery appends, using the registry supplied to that call.

Recovery requires no signing credentials. It either appends the reserved draft
at its original predecessor or recognizes that exact draft at its expected
ordinal, synchronizes the projection and checks the published cache. It does
not re-sign or append a duplicate. If later records exist, `head` still names
the adoption head; `observed_head` records the later tip. A reconstructed commit
labels its durability evidence as recovery evidence rather than claiming the
original append receipt was retained.

If recovery Full-verifies that another record has taken the reserved next
ordinal, it retires only that provably superseded intent and returns a stale
refusal. A caller can then prepare a fresh adoption at the new selected head.
Malformed intents also return a typed SDK refusal and remain in place for
operator inspection. Reviewed source, template and parameter pins must remain
intact during recovery, as they must for normal runtime declaration resolution.

The operation reconciles the already-published cache without rewriting it.
A changed cache or a post-append projection failure leaves a recovery boundary;
a durable append is not rolled back. Process-exit tests cover reservation and
append boundaries, not arbitrary power loss. Live writer coordination and a
representative user-store rehearsal remain separate from this SDK operation.

Adoption alone does not prove continuity for older boundary ticks. If preserved
legacy ticks would be consumed as current loop resets or vertex periods but
predate the adopted declaration, ordinary writes can refuse with
`BoundaryContinuityRefused`. Migration, adoption, reads and export can succeed
while writes remain unavailable. The loops real-store rehearsal demonstrated
this case; do not bypass the continuity check or silently discard those ticks.
A reviewed boundary cutover policy is separate work.

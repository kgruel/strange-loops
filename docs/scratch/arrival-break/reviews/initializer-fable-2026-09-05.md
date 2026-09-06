# Fresh initializer review — 2026-09-05

## Review status

**Locally reviewed; Fable verdict pending.** The requested tools-disabled,
source-attached `claude-fable-5-1[1m]` review did not yield a valid verdict.
Attempts encountered an unusable tool-shaped response, authentication failure,
and finally the session quota. No such output counts as a code review. The
configured session resets at 21:20 America/Chicago; refresh the source packet
before running it, because implementation has advanced since the early attempt.

## Current reviewed behavior

The scope is `engine.arrival_initialization`, the Arrival arm of the existing
`sdk.declare.init_vertex`, their typed results/errors and real temporary-store
tests. The supported path uses an explicit Authority descriptor and reserves
exact signed genesis/declaration content before minting. Physical lineage equals
the `_decl.genesis` fact ID. FACT and ARRIVAL signatures use separate domains;
SDK custom and default credentials receive the same verification checks.

The engine validates declaration grammar, semantics, documents and unchanged
residence before intent or custody writes. A PreGenesis report never proves
absence: the backend owns exclusive mint and refusal of conflicting existing
storage. File locations resolve relative to the vertex; custom adapter locations
remain opaque. SDK forwards an injected registry and honors location aliases.

Every recovery phase checks exact reserved custody content. Recovery reuses
reserved observer/descriptor/signatures and neither generates nor loads new
private keys. Lost keys cannot make recovery mint an unintroduced replacement.
Unknown append/mint and unwitnessed outcomes retain identity; postdurability
intent, projection and publication failures preserve known head/commit evidence.

Declaration publication writes/fsyncs a complete temporary file and exclusively
links it into place. Competing target bytes are never overwritten. Directory
open/fsync errors propagate. Primary reproduced the former silent directory-
open failure in both reservation-before-mint and postmint cases; both tests
failed before the fix. All **16 engine initializer tests** pass afterward,
including postmint recovery with the original lineage. Scoped Ruff passed.
Prior SDK integration checks cover custom signer domains, registry injection,
location/recovery options, safe KDL quoting and recovery without replacement keys.

## Additional declared keys

Primary completed the engine bootstrap follow-up: additional declared observer
keys are introduced by the founding observer before declaration genesis, in
one atomic append. Unsupported atomic size and malformed/conflicting founding
keys refuse before mint. Durable intent preserves exact introductions and
recovery verifies the full bootstrap without duplicating controls. The physical
lineage still equals the declaration-genesis fact ID; its ordinal can now be
later than one when introductions precede it.

All 21 engine initializer tests pass. A real engine initialization followed by
SDK emission as the additional observer verifies outer signatures from ledger
key history and the inner FACT signature under the separate domain. Full SDK
474 passed. The refreshed full-source packet and pending review receipt are in
[initializer-current-fable-2026-09-05.md](initializer-current-fable-2026-09-05.md).

SDK initialization still only scaffolds its default initial document set; a
caller-supplied rich declaration needs the final public initialization design.
Default mode selection and descriptor adoption remain pending the final cut.

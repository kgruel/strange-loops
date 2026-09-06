# initializer-current — Fable review

Effort: low. Finished: 2026-09-06T02:42:19.299175+00:00.
Packet SHA-256: `cfcd3b62a4c7ece71781c6a957299e8a33dc9b8b4c3f1e5a06aaa2e7d973cc32`.

Static reviewer output; findings still require primary triage.

No blocking findings. Four low-to-medium findings, all in implemented behavior; none touches deferred legacy cutover or empty-receiver import.

**1. Pre-mint open refusals strand a "reserved" intent (Medium).**
Location: `arrival_initialization.py`, `_continue`, reserved branch, the `registry.open(descriptor)` call before the `try: head = ledger.mint(...)`.
Trigger: the location already carries a binding whose journal remembers a head (StoreLost), the descriptor lineage disagrees with a presented genesis (NotAuthority from `_open_components`), the backend name is unregistered (UnknownBackend), or the binding probe is unanswered. All of these fire inside `registry.open`, which sits outside the mint `try`. With `head` still `None` and phase still "reserved", the outer handler re-raises the refusal raw.
Consequence: nothing was minted, yet the O_EXCL sidecar remains. The next `initialize_arrival` on that target refuses with `InitializationRecoveryRequired`, and `recover_arrival_initialization` re-opens and hits the same refusal. The operator must delete the sidecar by hand, and the SDK gives no hint that this is safe. This is inconsistent with the key-draft path, which performs the same open before `_reserve` precisely to refuse pre-intent. The same stranding applies when `mint` raises a `ContractRefusal`/`GenesisRefused` and `_head_and_check_genesis` fails: `raise mint_error from None` leaves the reserved sidecar behind with nothing committed. Suggested direction, not authorized here: either perform the attested open before `_reserve` on every path, or unlink the sidecar when the reserved phase refuses with a known precommit family and `head is None`.

**2. Concurrent reservation race surfaces as a raw `FileExistsError` (Low).**
Location: `initialize_arrival`, the `intent.exists()` check followed later by `_reserve`. `_reserve` correctly keeps `os.open(..., O_EXCL)` outside its cleanup `try`, so it does not unlink the winner's sidecar.
Trigger: two initializers for the same target both pass the `exists()` check before either reserves.
Consequence: the loser gets an untyped `FileExistsError` instead of `InitializationRecoveryRequired`. The SDK's `normalize_exception` passes it through unchanged, so the CLI reports an OS error rather than the "recover explicitly" identity. No durability harm; a diagnostic-identity gap only.

**3. Mint-unwitnessed recovery permanently downgrades the journal to first-contact (Low, design consequence worth stating).**
Location: `_continue` reserved branch, `NotWitnessed` arm, and `_head_and_check_genesis`.
Trigger: `AttestedLedger.mint` commits genesis but the bootstrap receipt write fails. The intent is not advanced to "minted". On recovery, `mint` is re-attempted, refuses, and `_head_and_check_genesis` opens a second attested handle. That open finds no binding and no journal, classifies FIRST_CONTACT, and writes a first-contact bootstrap.
Consequence: a store this machine actually minted is recorded as trusted on sight, which slice 6's mint-versus-first-contact check will read as the weaker claim. The `NotWitnessed` message already predicts this, so it is honest, but the initializer has enough evidence (the reserved genesis signature matches exactly) to justify a mint-level receipt on recovery. Not a bug against the stated design; flagging so it is a deliberate acceptance.

**4. `_bootstrap_matches` accepts a ledger that has grown past the bootstrap (Low).**
Location: `_bootstrap_matches` uses `current.ordinal >= len(drafts)` and checks only ordinals 1..n.
Trigger: recovery at phase "minted"/"declared"/"synced" after some other writer appended records beyond the planned genesis fact.
Consequence: recovery reports success with `head` at the foreign writer's ordinal and syncs the projection through it. The bootstrap records themselves are verified exact, so the declaration identity is intact and the seam's rollback/fork checks still ran at open. The result silently attributes a head the initializer did not produce; the result's `phase` and `head` do not distinguish this. Acceptable for a coordinator, but the exact-durable-intent claim would be tighter with `current.ordinal == len(drafts)` at phase "minted" (the append path already requires ordinal 0) and `>=` only for later phases.

**Checked and found sound for this stage:**
- Exact durable intent: genesis signature, drafts, and key drafts are reserved before mint and reused verbatim on recovery; `_reserved_genesis_signer` refuses any other digest, so recovery signs nothing.
- Separate signer domains: genesis and outer fact are verified against `arrival_verify`, inner fact against `fact_verify`; the SDK always supplies both verifiers and the tests pin the wrong-domain refusals before any intent or mint.
- Additional declared keys: refused pre-intent for malformed keys, founding-key mismatch, and conflicting duplicate keys; the atomic-limit check runs before `_reserve` when key drafts exist; the whole bootstrap lands in one `append` against expected ordinal 0.
- Failure identities: `OutcomeUnknown` carries `captured_head=None` pre-mint and the pre-append head post-mint; `Unwitnessed` carries the head without fabricating a commit; `CommittedIncomplete` is raised only when a head is known. The SDK error normalizer maps each to a distinct outcome and preserves `captured_head: null` explicitly.
- Ordinary opens keep every attestation refusal; restore-forward is reached only through the private `_open_components`, and no path skips `AttestedLedger`.

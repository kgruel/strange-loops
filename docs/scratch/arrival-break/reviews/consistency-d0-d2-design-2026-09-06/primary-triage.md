# D0/D2 design review — primary triage

Fable-low returned **REVISE** on the frozen design packet
`bacca7225908defa9df9c38ac75b1eca8cab2a34dd0d367fe0250f754a202769`.
The three design findings are accepted and resolved as implementation requirements;
the raw verdict is not rewritten as an external ACCEPT. The final implementation
review must assess these requirements in code and tests.

1. **Self-key introduction:** the subject may equal the introducing author.
   Existing authorized key K1 may introduce K2 for the same exact observer.
   K2 may not authorize its own introduction. The original table wording was
   incorrect, not a reason to change the existing additive-key protocol.
2. **Concurrency and interruption:** all provider mutations serialize under a
   provider-wide filesystem lock. A durable pending slot/token lookup identifies
   interrupted operations, which resume the same candidate or explicitly refuse.
   Binding publication uses a complete fsynced temporary file and no-clobber
   link. No automatic candidate deletion or unlocked reference-scan cleanup.
   Read-only resolution creates neither locks nor directories. Explicit
   maintenance/garbage collection is outside this implementation.
3. **Receipt signer absence:** no configured receipt observer means no TICK
   request. An unsigned tick remains legal before the signed-tick era. Existing
   signed-era policy requires a usable receipt capability and refuses preappend
   when absent. No implicit receipt identity from author, boundary, or custodian.

Additional primary decisions:

- Mapped initialization loads a binding explicitly prepared by a separate
  custody create/import operation. It creates no binding itself. Existing
  initialization recovery signs nothing and remains usable without custody.
- Mapped observer grant with no explicit public key refuses before effects;
  callers prepare a binding separately and pass its public key. This is the
  explicit pre-effect refusal option in the design, avoiding mixed custody and
  declaration partial effects. Legacy default behavior remains unchanged.
- Enforce coherent mapped configuration when constructing WriteCredentials;
  partial configuration cannot silently select legacy callbacks.
- SigningDomain-to-prefix composition stays in custody. Engine uses injected
  verification and neutral values only.
- Keep the existing exact-retry signature comparison in this slice. The
  review's retry ergonomics suggestion is a separate follow-up, not a reason
  to silently weaken equality during the binding migration.
- Recovery must not inspect current private bindings to claim readiness for
  future writes. Completion reports established initialization facts; later
  writes independently check their current binding against captured history.
- The design's implementation ordering is four dependent steps within this
  implementation stage, followed by one Fable-low implementation review.

No production changes were made before this review returned. These are concrete
contract refinements, so implementation may proceed without another external
design round; final adversarial review and independent tests remain required.

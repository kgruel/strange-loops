# followup — Fable review

Effort: low. Finished: 2026-09-07T00:41:47.557024+00:00.
Packet SHA-256: `f717b118ec76c00e3f0a216cb8b341ddc5439a2d69236cdab6dbc182992c6fdd`.

Static reviewer output; findings still require primary triage.

**Verdict: ACCEPT.** The blocker is closed; no remaining blocker or counterexample.

**Why the blocker is closed**

- The asserted reason string is emitted at exactly one site, `libs/engine/src/engine/credentials.py:222-229`, which is reachable only after the resolver returned a `ResolvedCredential`, its evidence passed shape/request checks, and the public key was compared against `authorized_keys`. Every other wrapping path (resolver exception, `None`, malformed evidence, signer/verifier failure) yields a different reason, so the test now distinguishes "provider failed" from "captured authorization refused".
- The binding evidence assertions at `libs/sdk/tests/test_arrival_mapped_workload.py:243-244` pin `key_ref` and `public_key` to the created other-tenant binding, and line 206 proves that key differs from Alice's authorized key. Combined with the exact request (234-239) and `use_position == verified ordinal + 1` (240-242), the refusal is provably the key-authorization check at the captured position, not a lookup failure.
- The independent preflight resolve (207-217) does not weaken this: the probe's `--allow-preflight` variant lets the first other-tenant resolve succeed and breaks the write-time one, and the test still fails with `AssertionError` because the write-time reason becomes "credential resolver failed" with no `binding` key. Before/after probe outputs match that analysis.
- Ordinal/lineage progress is asserted for grant, batch, and the post-relocation write (93-94, 122-123, 281-282), and head-unchanged checks follow each refusal (250, 265).

**Documentation claims**

- README limits `verify_target` to grammar, density, lineage, and hash chain and explicitly disclaims signature authorship, key trust, and projection agreement, matching `verify.py:53-57`. The "exact namespace and observer, independently of filename or lineage" claim matches what the test exercises.
- The scratch report now states the `Alice` control observes admission before credential lookup and that the case-distinct key is checked by a separate public resolve. The "three refusal controls exercise the same lifecycle" sentence is immediately qualified, so it no longer overstates.

**Optional suggestions** (not blockers)

- The `credential_binding` extractor walks up to three causal nodes and returns the first `CredentialBindingRefused`. In the current chain that is the outermost session wrapper, so the assertions are correct, but a comment in the test noting the reason belongs to the session-level refusal would make the intent obvious to a future reader.
- The scratch report's status header still says "focused follow-up review pending"; update it when this disposition is recorded.

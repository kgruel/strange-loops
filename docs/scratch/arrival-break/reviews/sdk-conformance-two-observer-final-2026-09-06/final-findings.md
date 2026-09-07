# final — Fable review

Effort: low. Finished: 2026-09-07T00:38:14.839727+00:00.
Packet SHA-256: `48dd3dfa74f8f5bb2d2aec2ae3590719928aa98200dc62fa1c8fc63037d2d59d`.

Static reviewer output; findings still require primary triage.

**Verdict: REVISE** (one small blocker; everything else optional).

**Blocker**

- **Wrong-namespace control can pass without exercising authorization.** `libs/sdk/tests/test_arrival_mapped_workload.py:198-215` asserts only `source_type == "CredentialBindingRefused"` and `details["captured_head"]`. Per `libs/engine/src/engine/credentials.py:165-181`, any resolver exception (unreadable custody root, malformed slot, broken `other-tenant` binding) is also wrapped as `CredentialBindingRefused` with the same captured head, so the test passes even if the other-tenant key was never resolved or compared. Counterexample: make `other_namespace.create_binding` write an unreadable slot so `resolve` raises; the test still passes. Fix: also assert `details["credential_binding"]["reason"] == "resolved public key is not authorized at the captured position"` and `details["credential_binding"]["request"] == {"namespace": "other-tenant", "observer": "alice", ...}`, and that the created other-tenant public key differs from `alice.public_key`. Evidence is already emitted by `errors.py:172-207`; nothing in production needs to change.

**Optional improvements**

- **Case-alias control is admission-only.** `Alice` is undeclared in the vertex, so `AdmissionFailed` is raised before any binding lookup (lines 217-230). It does not show that the `Alice` binding is selected independently of `alice` during a write. The doc wording is accurate, but "three refusal controls exercise the same lifecycle" overstates what this one touches. Either say so in the doc, or grant `Alice` with the alias key and assert a write succeeds with `signed is True`.
- **Ordinal progression is not asserted.** Heads chain by equality only. Adding `after.ordinal > before.ordinal` per commit (grant, batch, continued) and equal lineage would catch an idempotent no-op commit whose `after == before`.
- **No stray-store check after relocation.** Lineage pinning at `arrival_registry.py:540-554` means a freshly minted store would refuse, so this is covered indirectly, but an explicit `not (tmp_path / "relocated" / ".loops").exists()` makes the "absolute location keeps residence" claim direct.

**Existing API limitations, not slice failures**

- `emit_fact` Arrival preparation refusals surface as plain `AdmissionFailed` without `details` or captured head (`emit.py:485-492`), unlike the batch path's `AdmissionRefusal`. The doc's "available typed evidence" wording is correct; just note the asymmetry.
- `Full` verification excludes signatures/trust/projection by contract; the workload correctly compensates with exact read listings and the separate domain-signature tests.

**Claims checked and consistent**: head chaining across init, grant, batch, read, verify, relocation, and final write; batch receipts sharing captured head with `commit is None`; absolute store location preserved via `initialized.store.location` and `relocated_read.store.location`; fresh provider used for the post-move write; 13-test count matches 12 existing plus 1 new; README link path resolves from `libs/sdk/`.

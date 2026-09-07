# final — Fable review

Effort: low. Finished: 2026-09-07T02:47:42.324330+00:00.
Packet SHA-256: `fe6f874db5fec30babecabe70e3636b64686afb63226538b232d1873b5d81533`.

Static reviewer output; findings still require primary triage.

**ACCEPT.** No blockers found in the packet.

**What holds up**

- `main.py:263-283` orders transport parse → classification gate → provider construction → SDK write. Provider construction (`binding.py:245`) touches no filesystem, and `resolve` (`binding.py:436`) never mints. The test at `test_writer_boundary.py:44` proves neither resolver nor writer is reached on bad transport and no custody dir appears.
- Mapped-to-legacy downgrade is fail-closed in the SDK (`emit.py:396-397`, `698-699`), and the post-precheck swap test (`test_writer_boundary.py:113`) exercises exactly the documented race shape. The doc (`consistency-c9…md:53-66`) correctly calls the precheck a classification gate, not descriptor pinning.
- Exit mapping (`main.py:364-385`) checks `CommittedOutcome` before `TargetError`/`ArrivalRefusal`, so committed/unknown custody is exit 6 with `as_dict` details intact; the injected-boundary test asserts `fact_id` and `captured_head` survive. README exit text does not overclaim exit 4 as no-effects.
- Batch conversion fix (`emit.py:656-677`) raises `InvalidEmissionRequest` inside the prepare loop, before `_arrival_descriptor` at line 697; SDK test monkeypatches resolution to fail if reached. CLI test checks unchanged ledger bytes.
- `_descriptor_location` (`arrival_declarations.py:664`) now matches `descriptor_for` (`arrival_registry.py:153`) byte-for-byte on the File rule; non-File arm untouched. The SDK test covers unchanged alias accept and changed residence refuse with ledger bytes unchanged.
- The optional-signer contract is tested as stated: wrong-namespace key refuses with `CredentialBindingRefused` evidence; absent namespace yields `signed: false`, stored, custody snapshot unchanged.
- Scope claims are candid: legacy arms, suffix resolution, `JsonlStore`, reanchor all explicitly retained; the test-ordering caveat and harness assertion bug are disclosed rather than hidden.

**Optional observations** (no correction required for this slice)

- Stricter-than-before edge: a proposal that rewrites an absolute alias spelling to its resolved real path now refuses (same residence, different string). Fail-closed, consistent with `descriptor_for`, but worth one sentence in the doc's residence note.
- `emit_batch` still coerces `kind` and `origin` with `str()`/passthrough (`emit.py:653, 667`), so `"kind": 5` or `"origin": null` proceeds as `5`/`"None"`. Brief says accepted coercions are unchanged; flagging only that the README's "preserves each item's … origin" is loose for `null`.
- Doc inventory row cites `main.py#L134` for `_dispatch`; it is at line 248 now.
- README exit-2 sentence omits `SdkValueError` cases like the missing founding binding, which the test shows also exit 2. Accurate but incomplete.
- The wheel `installed_source_hashes` and "hashes matched" claims are recorded, not reviewer-verifiable statically.

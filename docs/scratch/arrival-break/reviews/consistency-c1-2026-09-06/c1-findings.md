# c1 — Fable review

Effort: low. Finished: 2026-09-06T17:00:27.994408+00:00.
Packet SHA-256: `b14de13d659a2aa8d780e42c458c169ab518757df293e74319c48d3014fc053f`.

Static reviewer output; findings still require primary triage.

**Verdict: accept.** The production diff is minimal and correct: all three entrypoints forward the caller's registry into the single descriptor opener, timeline forwards it to both the storeless aggregate route and the descriptor-root route, and the descriptor-root route passes `opened_root` so the root is captured once. No regressions found in the diff.

**Evidence quality.** The new test file exercises real `BackendRegistry` dispatch, not mocked engine entrypoints. The "opaque" opener registers through the public `register` path, so `BackendRegistry.open` still runs the default opaque binding, role capability check, lineage check, and the attested head seam. Locators with repeated slashes and a query string are asserted byte-for-byte on `store.location` and on the opener's observed `descriptor.location`, which confirms `descriptor_for` keeps non-file locations opaque. The single-root assertion (`calls.count(root_locator) == 1`) is discriminating: without `opened_root`, `capture_aggregate` would open the root a second time. Legacy poisoning of `resolve_target`, `probe_target`, and `with_builtin_backends` makes the no-fallback claims meaningful. Test counts and pass results are submitted evidence and were not verified here.

## Findings

**1. Low, existing limitation. Borrowed root is closed twice on the descriptor-root aggregate path.**
Source: `read.py:1515-1533`, `aggregate.py:385-388`, `arrival_aggregate.py:306-309,343-346`.
Scenario: `read_timeline` on a descriptor root whose effective declaration composes members. `capture_aggregate` appends the root as a `_CapturedNode` (line 306) even when it is the caller's `opened_root`, so `capture.close()` closes it, then `_open_arrival_read`'s `finally` closes it again. On a capture failure the root is also closed by the cleanup loop before the outer context closes it. The packet does not show whether `OpenedRead.close` is idempotent. The `opened_root` parameter predates this diff, so this is not a C1 regression.
Correction: have `capture_aggregate` mark the borrowed root as not-owned and skip it in both close paths, or add a test asserting close is idempotent.

**2. Low, test gap. "No built-in fallback" is only proven for a custom backend name, not for `file`.**
Source: `test_arrival_registry_injection.py:160-177`.
Scenario: every unknown-backend case uses `backend="opaque"` with an empty registry. The stronger consistency property, that a supplied registry without `file` refuses a `backend="file"` descriptor rather than reaching the built-in file adapter, is not asserted anywhere in the new file. The code at `read.py:105-106` clearly does not consult the built-in registry when one is supplied, so this is an evidence gap, not a defect.
Correction: add one parametrized case with a `backend="file"` vertex and `BackendRegistry()` expecting `UnknownBackend` matching `"file"`, with `_forbid_builtin_registry` applied.

**3. Low, documentation precision. README overstates where the registry applies.**
Source: `README.md` C1 paragraph; `read.py:1419-1420,1589-1590`; `declare.py:728`.
Scenario: a target with no descriptor (legacy store, or a storeless composition whose members are all legacy) routes to the legacy readers and the supplied registry is silently ignored. That is the intended "legacy unchanged" behavior, but "A supplied registry handles every supported root and member open" can be read as a refusal guarantee for those routes. Same for `inspect_declaration` on a malformed vertex, which falls to `probe_target` regardless of registry.
Correction: add one sentence stating that targets without an explicit descriptor keep legacy behavior and do not consult the registry.

**4. Low, coverage note. Default-registry compatibility is not asserted in the C1 file.**
Source: validation note lines 53-54.
Scenario: the claim that omitting `registry` still selects built-in backends rests on the existing SDK suite, which is reasonable since the default expression is unchanged at `read.py:106` and `aggregate.py:380`. No correction required for C1 acceptance; optionally add a single omitted-registry case in the new file so the contract is self-contained.

None of these block C1. Findings 1 and 3 are pre-existing; 2 and 4 are small evidence gaps. Aggregate refusals for entity and inspection are unchanged as required, and unknown backends surface as typed `UnknownBackend` from the registry without legacy or built-in fallback.

**Accept.**

# followup — Fable review

Effort: low. Finished: 2026-09-07T01:04:33.138246+00:00.
Packet SHA-256: `0ad7ef2e13d27c80278255c66b8c923945e8ce23bf73e6a35d8a82f71b833a14`.

Static reviewer output; findings still require primary triage.

**Verdict: ACCEPT.** No blockers. The four refinements are causally tied to engine paths and are not brittle or over-claimed.

**Traced checks**

- **Hook firing.** `injected_phases` is appended only inside the `after-append` branch, which the engine reaches at `arrival_declarations.py:1348` after the intent phase is durably `appended`. If `_replace_json` at line 1346 failed incidentally, the list would be empty and line 147 fails. The list has exactly one entry because the second edit refuses in prepare before apply (line 1041 arm), recovery never calls `apply_declaration_edit`, and the noop edit returns at line 1274 before any hook. This closes the causal-specificity finding more strongly than the OSError-type check.
- **Exact one record.** Adding a kind introduces no observer key, so `key_drafts` is empty; whether the diff yields one or several changes, lines 1114 through 1140 produce one envelope draft. Line 118 pins the captured head to `before_edit`, so `+1` is an exact identity.
- **Full projected list.** Line 228 now proves the recovered projection is exactly the baseline plus the retained fact IDs, which catches fresh-ID replay that the head equality could not. Row order follows plan change order, matching `fact_ids`.
- **Noop head.** Line 1276 returns `plan.captured_head`, which is the reconciled head since recovery appends nothing. Same comparison form as the pre-existing line 212, so no new type risk.

**Notes, non-blocking**

- Line 228 inherits a hidden coupling to `limit=20`. If a future strict init emits enough internal declaration rows to reach the limit, the assertion fails for a fixture reason. Native pass shows the count is within bounds; consider `limit=None` if the read API allows it.
- The restore at line 255 is redundant since the wrapper already passes through to noop, but it is harmless and makes intent explicit.
- Documentation stays inside scope: deterministic exception boundary, `after-append` only, poisoned mapped resolve and legacy `for_write` rather than constructors, and no production change. Full-suite evidence preceding the assertion-only edits is disclosed as such.

Logs treated as native evidence only. No execution performed.

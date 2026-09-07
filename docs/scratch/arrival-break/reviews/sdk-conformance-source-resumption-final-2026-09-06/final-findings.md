# final — Fable review

Effort: low. Finished: 2026-09-07T01:52:07.057371+00:00.
Packet SHA-256: `8a3fd0e1146360eaa2c085ccab15b285bffcc896c00d40e1518d77ba4b4d19e2`.

Static reviewer output; findings still require primary triage.

**ACCEPT.** No blockers.

**False-positive checks (none found):**
- Clock injection is real: `run_sources` resolves `execute_source_invocation` through the module global at `libs/sdk/src/sdk/sources.py:474`, so the monkeypatch at test lines 110-114 reaches the engine `clock=` parameter. Lifecycle timestamps 12.0/22.0 are therefore asserted, not assumed (`test:261`).
- Cadence decision is causally derived: `_latest_success` at `arrival_sources.py:351-357` only matches `status == "ok"`, so b's error lifecycle cannot satisfy its own cadence; `b_cadence.latest_success_id is None` (`test:265`) and `trigger_fact_ids == (a lifecycle,)` (`test:266`) pin the exact mechanism. Elapsed skip is pinned by `latest_success_ts == 12.0`, interval 3600, evaluated 20.0 (`test:260-263`), not by status strings alone.
- Upstream not rerun is enforced two ways: the collector's `assert invocation == "first"` would surface as a source error and break `resumed.status == "ok"`, and `attempts == Counter(a=1, b=2)` (`test:282`).
- Durable identity is exact: full receipt-order ID sequences compared (`test:190, 292`), uniqueness checked, per-field body equality (`test:195-209`), exact failed lifecycle payload including `invocation_id`/`source_index`/`returncode` (`test:213-223`), and all after-failure rows unchanged post-retry (`test:303`).
- Repeat-observation claim is explicit: `resumed_b_id not in failed_b_ids`, disjoint tier fact IDs, domain-fact set of exact size (`test:285-296`).
- Head/lineage chain: each tier's `commit.before` equals the prior head, bases match per-tier captures, verified head equals read head (`test:156-164, 228-229, 274-276, 308-309`).
- Fresh provider instance for the second invocation (`test:235-239`); isolated XDG/LOOPS_HOME roots (`test:25-29`).
- README additions stay within scope: no resume-token, no dedup, no exactly-once claim; the narrowed "without a terminal failure" durability wording is correct per `_result` at `arrival_sources.py:915-921`. Verification exclusions match `test:230-231`.

**Optional findings:**
- `test:226` is vacuous in the before-yield parameter (empty `failed_b_ids`). Consider also looking up `failed_b_source.lifecycle_id` so `read_fact_by_id` is exercised in both cases.
- `test:167` asserts no ticks/dispatches but nothing asserts `dispatch_status == "none"`; harmless, just a slightly weaker pin than the README wording.
- Scratch doc line 27 names Sol/Terra/Luna roles; fine for scratch, but not something the README should inherit.

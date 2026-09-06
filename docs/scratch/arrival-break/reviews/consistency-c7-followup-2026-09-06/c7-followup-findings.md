# c7-followup — Fable review

Effort: low. Finished: 2026-09-06T22:39:26.826950+00:00.
Packet SHA-256: `6a9782c20ad0120d9c41f13f4f8c2ecb27821fab315979d23a56c48cebb221c2`.

Static reviewer output; findings still require primary triage.

**ACCEPT**

No blockers. The bridge now makes a single parse through `_arrival_definition`, and the retained AST/descriptor tuple is what summary, state, and timeline carry into `_open_arrival_read` and `_arrival_declaration`. Nothing downstream re-reads the locator file on the Arrival path, so the replacement cannot redirect residence.

**Preserved contracts, verified by reading the call chain**
- Explicit role refusal at `libs/sdk/src/sdk/target.py:91` runs before the aggregate check, so the old bridge's post-reparse role check was already redundant. Behavior is equivalent.
- Default single-store refusal is intact. `_arrival_descriptor` still defaults `allow_aggregate=False`, and only the bridge opts in.
- Unknown registry refusals, CURRENT requirement, and custody stay inside `open_read`, which is untouched.
- Effective-root topology selection at `read.py:539`, `read.py:963`, and `read.py:1501` still decides shape from the bounded declaration, not the locator.
- Malformed and legacy fallbacks are unchanged. `_arrival_definition` still returns `None` on parse failure, and the old bridge's malformed-reparse re-raise path is gone because there is no reparse.

**Test adequacy**
- Monkeypatching `sdk_target.parse_vertex_file` hits the name `_arrival_definition` actually binds, and `calls == 1` proves the single parse in the target module.
- The replacement is a well-formed aggregate locator pointing at a missing residence, so a regressed resolver fails loudly rather than passing by accident. The disclosed pre-fix probe confirms the three failures.
- Asserting `store.location == str(log.path)` and `captured_head.lineage` pins both residence and basis to the original descriptor, which is the actual property at stake.
- The local file left after `sync_target` is a descriptor-bearing `discover` aggregate, so `has_local_descriptor_aggregate` returns `False` at `aggregate.py:420` and the test exercises the bridge, not the storeless route.

**Notes, non-blocking**
- The test only covers replacement after the target parser returns. Replacement between `has_local_descriptor_aggregate` and the bridge remains a separate observation, as the summary already states. Behavior there is benign since the bridge would simply parse the new file.
- The full SDK run preceded the one-line fixture refinement. The refinement is test-only and the production hash is unchanged, so this is acceptable, but rerunning the full suite once before checkpointing removes the caveat.
- Removing `descriptor_for` and `parse_vertex_file` imports from `read.py` is consistent with Ruff passing. If either were still referenced, Ruff would have flagged an undefined name.

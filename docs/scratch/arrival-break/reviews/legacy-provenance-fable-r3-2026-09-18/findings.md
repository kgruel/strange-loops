**ACCEPT.** There are no P1 or P2 blockers. This was a static trace with no tools, and I ran no tests.

## Closure

| # | r2 finding | Status | Trace |
|---|---|---|---|
| 1 | Post-S bad window | **Closed** | `review:321-331`: `prior` is now `t2`, so the predecessor check at `verify:249` passes. The `f2`→`f2` cursors pass continuity at `:253`, with `lo=hi=2`. The window is sha256 of nothing, which differs from `"0"*64`, so it refuses at `:561-564`. The match `post-migration tick window mismatch` pins it. |
| 2 | Eligible row left unmapped | **Closed** | `review:169-193`: the source has two blank-observer facts. The first is genuinely transformed and consumes the one manifest entry. Coordinates 2–4 are clean, with the `t1` window counted as explained. Coordinate 5 is byte-identical with no entry pending, so `:379` is skipped and `:384-387` fires. Source and output hashes stay consistent, and `_verify_sources` refuses before the five-row/S mismatch is reached. The match is `eligible line`. |
| 3 | Reversed window | **Closed** | `review:256-275` with `("f1","")`: the predecessor is unchanged and valid. `row[7]="f1"` equals the last cursor, so `:253` passes. With `lo=1` and `hi=0` it refuses at `:259-262`, and the match is `reversed window`. The sibling `("","f2")` case hits `:253` and matches `cursor discontinuity`. |
| 4 | Mutated or reordered prefix | **Closed** | `review:89-125, 235-242`: the log is genuinely re-minted with the same lineage and key, and S is re-pinned, so the walk, genesis signature, lineage and `rh` checks all pass. Both variants refuse at ordinal 1 on `:523-527`, the mutated one on payload and the reordered one on tick versus fact. The mutated case guards a real hole: without that check it would pass, because the changed fact still explains the `t1` window. The reordered case would refuse elsewhere and miss the match. |
| – | Forged key introduction match | Closed | The match `signature` hits the `:460` message. |
| – | Plan wording | **Closed** | `plan:50-52, 129, 299` use distinct `ORIGINAL_SOURCE_SHA256`, `ORIGINAL_VERTEX_SHA256` and `CANDIDATE_VERTEX_SHA256`, and no stale `ORIGINAL_SHA256` or `CANDIDATE_SHA256` remains. `plan:245-251` requires `arrival.captured_head` to equal A in all three fields and names `arrival.sha256` as the rollback pin. That is consistent with `verify:492-496, 592` and the rollback precondition at `plan:369-371`. The 982 affected-row count and the disablement-record wording are both present. |

## Basis and limits

- **Test count:** the final files collect 9 base cases and 22 review cases, which matches the supplied `focused_provenance_and_review: 31 passed`. That is the r2 count of 29 plus the two new re-mint cases.
- **Sources not supplied:** I did not see `jsonl_codec`, `ArrivalLog` or `prepare_legacy_unattributed.py`. So I cannot confirm that the hand-built `f-extra` JSON keys decode, or that an `""` end cursor survives the codec round trip.
- **Why that does not block:** every one of the four paths now carries a precise `match=`. A miss on a neighbouring check would show up as a test failure in that receipt, not as a silent pass.

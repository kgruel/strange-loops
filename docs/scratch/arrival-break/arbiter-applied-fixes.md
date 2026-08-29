# Arbiter-applied fixes — arrival-break arc

Pipeline rule: arbiter-applied fixes have no independent gate; sol is their only
independent verification. Every entry here MUST appear at the top of the next sol
brief's unverified-fixes table. Remove entries only when a sol round has PASSed them.

| commit | finding | fix | arbiter verification |
|---|---|---|---|
| e7513164 (wave branch) | slice-2 integration seam: WP4's WP2-anticipating pin (`assert not isinstance(ledger, ArrivalLedger)`) failed once WP2 landed replicate/export — WP2 flipped WP1's copies but could not reach WP4's parallel branch | pin flipped to positive form + comment rewritten | the pre-fix state IS the failing mutation, observed twice in the integrated engine suite; post-fix engine 2062+1s green. Rides the WP5 sol brief's unverified-fixes table |

## Verified (sol-PASSed, removed from the open table)

| commit | finding | sol round |
|---|---|---|
| 8aa4c619 | `finding:engine-tests-masked-sign-dependency` — engine conftest's masked dep on sign | slice-1 sol-LOW r1 PASS (2026-08-29): dep declared dev-only, runtime metadata clean, no runtime engine source imports sign — `sol-slice1-r1-stdout.log` |

# Arbiter-applied fixes — arrival-break arc

Pipeline rule: arbiter-applied fixes have no independent gate; sol is their only
independent verification. Every entry here MUST appear at the top of the next sol
brief's unverified-fixes table. Remove entries only when a sol round has PASSed them.

| commit | finding | fix | arbiter verification |
|---|---|---|---|
| *(none open)* | | | |

## Verified (sol-PASSed, removed from the open table)

| commit | finding | sol round |
|---|---|---|
| b2c35955 | S3I-L-5 correction: §04b fence-cost sentence, sol's wording verbatim (per distinct eligible fenced ordinal) | slice-3 integration sol-LOW r4 PASS (2026-08-30): "neither overclaims nor underclaims" — `sol-s3-integration-r4-stdout.log` |
| b98ec734 | `_degraded` docstring: "incomplete read is PERMANENT" → persists-until-operator-acts (amendment #5 catch-up; doc round 2's flag) | slice-3 integration sol-LOW r1 PASS (2026-08-30): paragraph agrees with shipped behavior, remainder of the docstring consistent — `sol-s3-integration-r1-stdout.log` |
| e7513164 | slice-2 integration seam: WP4's WP2-anticipating protocol pin flipped to positive form | slice-2 WP5 sol-LOW r1 PASS (2026-08-29): diff confirmed one assertion + comment; sol's own mutation (rename FileLedger.replicate) makes the flipped pin fail — `sol-s2wp5-r1-stdout.log` |
| 8aa4c619 | `finding:engine-tests-masked-sign-dependency` — engine conftest's masked dep on sign | slice-1 sol-LOW r1 PASS (2026-08-29): dep declared dev-only, runtime metadata clean, no runtime engine source imports sign — `sol-slice1-r1-stdout.log` |

## Caught (the no-gate path's verification firing — kept as the supersession receipt)

| commit | what happened |
|---|---|
| 32234eac | §04b fence-cost sentence FAILED sol integration r3 as S3I-L-5 ("one lookup per abandoned anchor" overclaimed vs per-distinct-eligible-ordinal) — corrected at b2c35955 with sol's wording, PASSed r4. Second arbiter-applied prose fix caught by sol in one round; the path's only verification is sol, and twice now it has fired. Keep the path rare. |

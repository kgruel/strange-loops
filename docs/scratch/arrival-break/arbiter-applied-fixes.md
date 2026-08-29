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
| e7513164 | slice-2 integration seam: WP4's WP2-anticipating protocol pin flipped to positive form | slice-2 WP5 sol-LOW r1 PASS (2026-08-29): diff confirmed one assertion + comment; sol's own mutation (rename FileLedger.replicate) makes the flipped pin fail — `sol-s2wp5-r1-stdout.log` |
| 8aa4c619 | `finding:engine-tests-masked-sign-dependency` — engine conftest's masked dep on sign | slice-1 sol-LOW r1 PASS (2026-08-29): dep declared dev-only, runtime metadata clean, no runtime engine source imports sign — `sol-slice1-r1-stdout.log` |

# sol HIGH review — JSONL-canonical store, round 2 (post-remediation + simplify)

Repo: /Users/kaygee/Code/loops, branch feat/010-surfacing.
Diff under review: `git diff 71bc36c...HEAD` — now 26 commits. Since your r1
(which reviewed through 4364832): 6 remediation commits (fb38066..776554b)
answering your r1 findings 1–6, then 7 quality-pass commits (5dfc081..b310e71)
from a 4-angle simplify review. Design contract unchanged (see r1 brief:
docs/scratch/010-wave/sol-jsonl-brief-r1.md).

## Primary: verify the r1 remediations

Per-finding, empirically where you can (your r1 fault-injection scenarios are
the templates):

1. fb38066 — post-fsync orphan line: no append may stamp past an unindexed
   durable line. Re-run your 3-append middle-insert-fails injection.
2. 254171a — read resolution tails a behind index (existing .db no longer
   short-circuits). Re-run your durable-second-line + resolved_index probe.
3. 730ab3e — claims corrected, not detection extended: docs now state
   open-time detection covers inserts/count-drift/last-line only; interior
   tampering of SEALED facts is verify_chain's job (pinned by
   test_interior_sqlite_tamper_of_a_sealed_fact_survives_open_but_fails_verify
   and, honestly, test_interior_tamper_of_an_unsealed_fact_is_caught_by_nothing).
   Check the corrected claims are now accurate.
4. 3a75aed — codec symmetry: dup keys rejected, serializer validates the
   decoder's domain (ts="1.0" refused at append). Re-run your probes.
5. 359e45a — apps/tasks routed through the authority switch.
6. (minor) negative offset → rebuild, not OSError.

## Second: the simplify commits must be behavior-preserving

5dfc081..b310e71 were quality-only (dedup, composition, spec-table collapse,
SQL-spelling unification, meta accessors, residence relocation, dispatcher
refusal backstop, three micros, rebuild_jsonl dissolved into the engine path).
Two accepted behavior deltas, both flagged deliberate: (a) constructor-raised
JsonlCanonicalUnsupported in store verbs now renders as a clean refusal
(rc=2) instead of a traceback; (b) rebuild_jsonl's output store is born with
offset/count markers stamped. Everything else must be observationally
identical — hunt for accidental deltas, especially in jsonl_codec._SPEC
error-message/validation parity with the pre-collapse functions and in the
resolver compositions (resolve_store_path = ensure_index(resolve_canonical_path),
same in commands/resolve.py — the open-coded combine recursion was deleted;
confirm combine/discover aggregation resolution behaves identically).

## Third: a named open finding — adjudicate it

Surfaced during the simplify apply: `sl store verify` (and stats/ticks) read
through StoreReader / plain SqliteStore over the INDEX. On a store carrying an
out-of-band sqlite row (which open-time detection would refuse), verify prints
"✓ chain intact" rc=0 — it never constructs a JsonlStore, so the refusal never
fires, and it verifies the poisoned index rather than the canonical log.
Sealed-window tampering IS still caught (window hashes); an out-of-band
INSERT of a plausible row is not. Adjudicate: is verify-the-index the right
contract (with the log's word only via rebuild), or should verify on a
jsonl-canonical store check index-vs-log agreement (e.g. count/offset parity,
or a full line-hash walk as an opt-in --deep)? Recommend a shape; don't
implement.

## Ground rules

Same as r1: empirical verification, scratch dirs only, do NOT touch
.loops/data/. Full suites are green at HEAD (engine 1257, loops 2421+1xf,
store 106, tasks 261, arch 59). Report: per-remediation verdict,
regressions found (file:line, severity, scenario), and your adjudication of
the verify-scope question.

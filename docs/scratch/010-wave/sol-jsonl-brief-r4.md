# sol HIGH review — 0.10.0 roll-ins, round 4

Repo: /Users/kaygee/Code/loops, branch feat/010-surfacing.
Scope: `git diff 86be91e...HEAD` — 8 commits, two work items. Everything
before 86be91e is converged (your r1–r3 + dispositions). Full sweep green:
engine 1284, loops 2440+1xf, store 111, tasks 269, arch 59.

## Item 1: verify-canonical-agreement (c0504ce, 10bd70d, 0437c40, 49a1cd0, e41e1c5)

Implements design/store/verify-canonical-agreement (ratified): L1 agreement
gate (offset/counts/last-line parity) default on jsonl-canonical stores,
rc=1 + named divergence + suppressed "chain intact" on disagreement; L3
honest labels ("index chain intact; canonical parity checks pass (not
deep)"); --deep streams the log, compares content+order against rowid-walked
index rows, re-derives the chain from canonical content (2.5s on the live
111MB store); stats/ticks gated the same way. engine/canonical_audit.py is
the pure-reader module — no JsonlStore construction anywhere in the
verify path (constructor repairs; repair destroys evidence).

Priority re-checks — the final internal fix rounds were applied UNVERIFIED:

1. 49a1cd0 answered: (a) last-line check judged the last line IN THE FILE
   not the last line CONSUMED (offset < size false-tamper); (b) benign
   writer windows (index lag post-fsync, torn tail) indistinguishable from
   tamper — the fix introduced a lag-vs-tamper distinction. Verify the
   distinction judges the CONSUMED prefix and reports lag honestly without
   opening the false-negative door.
2. e41e1c5 answered: lag verdict was decided solely by the offset marker
   read from the artifact under suspicion — rewinding the marker one
   integer downgraded tamper to benign lag. The fix "corroborates against
   the log" and "heals a rewound marker". Adversarially probe the
   corroboration: can any single-artifact edit (index-only or log-only)
   still buy a benign verdict? Marker rewind + row edit inside the
   now-"lagging" suffix?
3. Unadjudicated internal minor: `sl read` (the primary read surface) is
   ungated — serves a poisoned index rc=0. Adjudicate: acceptable residue
   for this release (read is not an attestation verb; verify/stats/ticks
   are) or a gap? Recommend, don't implement.
4. --deep semantics: first-divergence break vs full walk (internal minor
   said the chain walk starves after an early content failure) — was that
   fixed or accepted? Is the reported divergence (line number + id) right?
5. The advertised remedy string ("catch the index up with loops read")
   crashed unhandled per an internal finding — verify the current remedy
   path works on a lagging store.

## Item 2: tasks-residence (b7d44c0, 88fe23b, 3963ad6)

Readers now pass an explicit canonical `store=` override through
vertex_read/vertex_facts/vertex_ticks/vertex_summary (new engine keyword,
resolved via resolved_index — declaration answers WHAT, cwd answers WHERE).
All 8 tasks-vertex reader call sites converted (dashboard + follow paths in
88fe23b after fault-injection found 5 of 8 reversion-transparent); 3963ad6
ratchets the discipline structurally.

Re-checks: (a) the un-masked scenario — packaged-style vertex, workspace
cwd, write then read WITHOUT patching module state, both .db and .jsonl
declarations; (b) the ratchet test — does it actually fail when a call
site drops store= (try removing one), or is it enumeration that drifts?
(c) the relative-store= resolution minor (resolves against the vertex dir,
not cwd) — fixed or a documented trap?

## Ground rules

Empirical, scratch dirs only, do NOT touch .loops/data/ (read-only
verify/--deep against the live store is fine — it is a pure reader; confirm
it leaves mtime/bytes untouched). Report per-item verdicts, new findings
file:line + severity + scenario, and CONVERGED / NOT CONVERGED for the
roll-in scope.

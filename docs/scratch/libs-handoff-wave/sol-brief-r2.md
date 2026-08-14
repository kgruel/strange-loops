# Sol review brief — libs-handoff-wave, round 2

## 1. Anchor

- Repo: this checkout, branch `libs-handoff-wave`.
- Full diff remains `git diff main...HEAD`, but your r1 findings are all
  dispositioned — round 2's PRIMARY target is the remediation commits
  (`git log --oneline` since the r1 stdout commit; the five fix commits are
  26611005, f9728a94, dd1e5b4b, 05c8323c, ceb0f02e on the merged
  fix/libs-handoff-r1 branch). Fixes deserve MORE adversarial attention than
  first-cut code — construct evasions of them specifically.

## 2. Contracts

Unchanged from r1 (docs/scratch/libs-handoff-wave/sol-brief-r1.md §2):
LIBS_CHANGES + the arbiter modifications, the ratified ceremony encoding
(batch grammar NON-NEGOTIABLES), attestation-from-committed-row.

## 3. R1 disposition table (verify each, then hunt holes IN the fixes)

| Finding | Fix | Disposition to verify |
|---|---|---|
| R1-01 blocker: single-line sibling deletion | 26611005 | add-expansion now splits every top-level child (new kdl_split_top_level_nodes, quote/escape/brace-aware); edit/remove fail-loud when a physical line carries siblings. Evasion ideas: strings containing `;`/`}`/braces, escaped quotes, comments on the shared line, nested blocks inside a single-line child. |
| R1-02: LIKE wildcards in kind filters | f9728a94 | Exact-or-substr prefix at THREE sites (query_facts, facts_between, vertex_reader UNION ALL). Check for a fourth site anywhere else (search paths, FTS, ls). |
| R1-03: preflight RTO raw codec leak | dd1e5b4b | (JsonlCodecError, UnicodeDecodeError, OSError) → typed "unreadable" with pre-recovery report. Evasion: exception types outside that tuple reachable through recovery (sqlite3 errors? MemoryError-shaped? declaration resolution errors?). |
| R1-04: canonical writability | 05c8323c | TargetInfo.canonical_writable added (writable keeps probed-path meaning); plan gates on both; apply refuses typed BEFORE intent creation. Evasion: writability races (chmod between plan and apply), read-only DIRECTORY vs read-only file, jsonl log writable but index dir not. |
| R1-05: serializer contract narrowed | ceb0f02e | Ruled narrow-the-claim (zero corpus usage). Verify no remaining overclaim in any docstring/doc; the refusal is pinned as contract. Do NOT re-litigate the ruling itself. |

## 4. Also in scope

- Any regression the fixes introduced elsewhere (the r1-fix branch touched
  population.py, store_reader.py, vertex_reader.py, preflight.py, probe.py,
  ceremony.py, vertex_mutation.py).
- Anything major you saw in r1 but deprioritized below the five reported.

## 5. Verdict format

Per finding: id (SOL-R2-NN), file:line, severity, claim, empirical evidence,
fix direction. End with CONVERGED / NOT CONVERGED (zero new blocker/major and
all r1 dispositions verified sound).

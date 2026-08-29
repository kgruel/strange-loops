# Sol review brief — arrival-break slice 2 / WP2 (replicate/export/import), round 1 (per-WP, LOW)

You are the cross-family reviewer for slice-2 WP2. Review the WP diff adversarially for
correctness against the design contract. You review and report — no fixes, no commits.
Run tests and scripts to verify claims empirically (preferred over reading alone).

## 1. Anchor

- Repo checkout: this working directory (a git worktree of /Users/kaygee/Code/loops).
- Branch: `slice2/wp2-replicate`, tip `165d86ea` (6 commits over wave base `0d38c969`).
- Diff spec: `git diff 0d38c969...165d86ea`.
- Suites: engine per-package (`.venv/bin/python -m pytest libs/engine/tests -q`).

## 2. Design contract (what the code must honor)

From `design:arrival-break-slice2-backend-contract` (ratified,
`01M177MHWHD5HM574VSTDE17X8`) §A.2 + §D.2:

1. **`replicate` is COMPOSITION, not greenfield** (SD-3): carried-in records pass the
   same validates-never-assigns posture as `append_record` — supplied `rh` checked,
   never trusted; full-head CAS pin; typed same-height-fork refusal (`ForkedHeight` →
   `SameHeightFork`, deliberately NOT an `AppendRejected` so merge's retry family
   cannot spin on a fork). No second appender: the batched machinery is the shared
   `_append_many_under_lock` (a loop over `append_record` would deadlock — flock is
   per open-file-description).
2. F1's site-B CAS moved INTO that shared writer so replication inherits WP1's
   full-head pin; site A untouched; both sites remain independently mutation-testable.
3. `export`: dense prefix, byte-exact — `b"".join(records)` equals the log's own
   prefix bytes; manifest carries no clock/host.
4. Minimal portable import, §08 default ONLY: new empty replica (via `adopt_genesis`,
   which SHARES mint's O_EXCL ceremony — no second genesis path) or exact prefix
   agreement through the target's head, else refuse. Import does its OWN §08 agreement
   check over `scan` (replicate's fork check only sees the overlap it is handed — an
   empty remainder would bless a fork in silence).
5. Three replicate vector families in `spec/conformance/vectors/replicate/`:
   exact-suffix accept; same-height-fork refuse; catch-up preserves hashes
   byte-for-byte. The signature is the discriminator that makes assign-vs-validate
   observable on an exact suffix — stated in SCHEMA.md as a family property.
6. `capabilities()` honest: REPLICA joined AUTHORITY, `export_codecs=("arrival-jsonl-v1",)`,
   ARCHIVE absent. `import_prefix` off the Protocol (the ratified §03 table has nine
   rows) but in `LEDGER_MUTATIONS`.

**NON-NEGOTIABLES**: no second appender or genesis path; wire codec and
`content_commitment` semantics untouched; the 14 arrival test files unmodified;
store package untouched (store 180).

## 3. Unverified fixes — verify empirically, top priority

| commit | claim | your job |
|---|---|---|
| 165d86ea | Gate F-1 (test asserted on `__protocol_attrs__`, a 3.12+ typing internal, vs requires-python >=3.11): respelled via `_declared_surface()` — plain vars()+annotations introspection; RATIFIED_LEDGER_OPS a written-out literal; adapter subset vs Protocol exact-equality split; both mutation directions demonstrated (tenth op added → left-set failure; `export` dropped → right-set failure with isinstance still TRUE — the property the runtime check cannot buy). Test-only commit. | Re-run both mutation directions yourself. Confirm no typing internals remain (grep `__protocol_attrs__`). Confirm the commit touches only the test + report. Confirm the query-separation test still derives from `LEDGER_MUTATIONS`. |

## 4. Prior review state (gate, already run — do not re-litigate; flag if unsound)

Gate PASS at 1d0fc887: all three vector-family mutations reproduced with the negative
controls green (the unsigned catch-up vector staying green under the re-coordination
mutation is the signature-discriminator proof); F1 independence re-derived at both
current homes; import's own agreement gate proven load-bearing (empty-remainder fork
accepted in silence with it no-op'd); `adopt_genesis` single-ceremony verified;
flock deadlock rationale proven by measurement (3s block); export byte-identity direct.
Dispositioned: F-2 (import cannot progress while max_atomic_records < remainder —
resumable import is contract-implied) → slice-gate contract-text package, with WP2-D1's
op-row question. G-noted: `merge.py:308` retries on AppendRejected only, so ForkedHeight
cannot spin (pre-emptive taxonomy — merge calls append_marked_many today).

## 5. Seeded review targets

- Torn-tail interaction: replicate/import onto a log whose tail is torn (partial last
  line) — refusal or misbehavior? WP1's verify refuses; what do the new write paths do?
- `import_prefix` into a target that is BEHIND the import's manifest but whose overlap
  agrees — the catch-up path — is the agreement check over the full overlap or only
  the head?
- Concurrency: replicate racing an ordinary append — the CAS pin should refuse cleanly;
  construct it.
- The family-completeness check in test_conformance_replicate.py: does it actually fail
  if a vector file is dropped from the directory?

## 6. Verdict format

Per §2 item: PASS/FAIL + evidence. §3: PASS/FAIL. New findings: `S2WP2-L-<n>`,
file:line, severity (BLOCKING/NON-BLOCKING), concrete failure scenario, evidence.
Then one line: **CONVERGED** or **NOT CONVERGED** (with the blocking list).

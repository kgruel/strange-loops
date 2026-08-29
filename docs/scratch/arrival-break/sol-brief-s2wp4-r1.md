# Sol review brief — arrival-break slice 2 / WP4 (KDL backend arm + registry), round 1 (per-WP, LOW)

You are the cross-family reviewer for slice-2 WP4. Review the WP diff adversarially for
correctness against the design contract. You review and report — no fixes, no commits.
Run tests and scripts to verify claims empirically (preferred over reading alone).

## 1. Anchor

- Repo checkout: this working directory (a git worktree of /Users/kaygee/Code/loops).
- Branch: `slice2/wp4-kdl-registry`, tip `91835e7b` (6 commits over wave base `0d38c969`).
- Diff spec: `git diff 0d38c969...91835e7b`. 14 files.
- Suites: lang (`.venv/bin/python -m pytest libs/lang/tests -q`), engine, and
  `tests/architecture` from the root env.

## 2. Design contract (what the code must honor)

From `design:arrival-break-slice2-backend-contract` (ratified,
`01M177MHWHD5HM574VSTDE17X8`) §B + §D.4:

1. KDL: `store "<path>" backend="file"` — location stays positional, `backend=` a
   property; bare `store` keeps meaning what it means today. New frozen `BackendDecl` +
   `VertexFile.store_backend`; **`VertexFile.store` UNTOUCHED**.
2. Parse REFUSES: unknown property on `store`, a child block, empty/blank backend —
   ParseError in the loader's established style (today's silent prop-discard was the
   hazard). Stored backend name is stripped (pinned since 91835e7b).
3. **The backend name is residence**: threads as a third residence parameter through
   `documents_to_vertex` and `engine/declaration.py` (all rebuild sites, including
   `_reattach_ingress` and `program.py`); it NEVER enters `_decl.*` payloads.
4. `engine/arrival_registry.py`: three ruled arms — explicit wins, NO suffix
   cross-check; inferred-arrival transitional (slice-5 deletion marker); jsonl/sqlite →
   None, never routed through the registry. Plus the store-less fourth arm → None.
   UnknownBackend raised only in `open`. No import-time registration; re-register
   refuses; adapters imported lazily (subprocess-pinned).
5. Parity probe over every tracked `.vertex` + minted fixtures covering both arrival
   arms at two levels (descriptor names the same log; ledger is over it).
6. `residence.py` diff-empty. No consumer rewiring (nothing in production paths calls
   the registry). No role/lineage parsing (role= actively refuses). Rule 18: registry
   registered (WP1's completeness ratchet forced it).

## 3. Unverified fixes — verify empirically, top priority

| commit | claim | your job |
|---|---|---|
| 91835e7b | Gate F2+F4: strip normalization pinned by a stored-value assertion (mutation demo: unstripped-store variant → exact BackendDecl mismatch failure; production loader.py diff EMPTY vs pre-gate — test-only fix); `_residence_stripped` docstring/spacing corrected. | Re-run the mutation (move the strip into the blank-check only) → the new test must fail; restore. Confirm `git diff ff86a2b4 91835e7b -- libs/lang/src libs/engine/src` is empty. |

## 4. Prior review state (gate, already run — do not re-litigate; flag if unsound)

Gate PASS at ff86a2b4: all four mutation demos reproduced (unknown-prop refusal;
threading drop → 4 named failures; ingress-carry drop → ONLY its test across the full
2016-test engine suite; Rule-18 ratchet naming the unregistered module); the
`_frozen`-defeats-`dataclasses.replace` root cause confirmed empirically; builder.py
non-carry bounded (no seeding path — nothing to lose); registry-open-needs-a-projection
reproduced and correctly LEFT for the slice gate's F2 ruling; parity probe scoping
verified honest (zero tracked arrival-canonical .vertex). Dispositioned: F1
(descriptor_for call-time import via residence's pre-existing engine.arrival coupling)
→ WP5 doc pass; F3 (KDL typed-value coercion, `backend=null` → a backend named 'None')
→ slice 5 adopt design.

## 5. Seeded review targets

- The three rebuild sites (documents_to_vertex, _reattach_ingress, program.py): is
  there a FOURTH path that reconstructs VertexFile and could drop store_backend —
  including in tests' helpers or any `_replace`-alike? The finding's own generalization
  (constructor-completeness ratchet) is slice-5 work; here just hunt for a missed site.
- The transitional inferred arm: can it fire for a store that is NOT arrival-canonical
  (e.g. a path whose canonical_mode misreads)? Construct edge paths.
- Descriptor equality/identity: `descriptor_for` on the same vertex from two cwds —
  relative-location resolution stable?
- The registry refusal messages: do they leak filesystem paths into errors that might
  end up in signed payloads anywhere?

## 6. Verdict format

Per §2 item: PASS/FAIL + evidence. §3: PASS/FAIL. New findings: `S2WP4-L-<n>`,
file:line, severity (BLOCKING/NON-BLOCKING), concrete failure scenario, evidence.
Then one line: **CONVERGED** or **NOT CONVERGED** (with the blocking list).

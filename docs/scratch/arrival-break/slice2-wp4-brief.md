# Slice 2 / WP4 impl brief — KDL backend arm + registry + parity probe

Arc: `design:arrival-break-implementation`. Slice contract:
`design:arrival-break-slice2-backend-contract` @ `01M177MHWHD5HM574VSTDE17X8` (ratified).
Full design: `docs/scratch/arrival-break/slice2-design-proposal.md`. **Your sections:
§B (all four subsections — B.3's refusals and B.5's residence threading are the two
hazards this WP exists to close), §D.4.** WP1's `arrival_contract.py` gives you
`StoreDescriptor` and the Protocols; `arrival_registry.py` is YOURS to create (WP1
deliberately did not — the Rule 18 completeness ratchet will fail until you register
it; that failure firing is by design). Deviations are reportable (finding fact +
report), never silent.

## Scope (proposal §B + §D.4)

1. **`lang/ast.py`**: frozen `BackendDecl(name: str)`; `VertexFile.store_backend:
   BackendDecl | None = None`. `VertexFile.store` UNTOUCHED.
2. **`lang/loader.py`**: parse `backend=` property on `store`; REFUSE unknown
   properties, REFUSE a child block, REFUSE empty/blank backend value — `_error`/
   `ParseError` in the `loader.py:849` style (SD-4: today props/children are silently
   discarded and nothing pins that).
3. **Residence threading** (SD-5): `documents_to_vertex(..., store_backend=...)` third
   residence parameter; `engine/declaration.py` both call sites pass it. The backend
   name NEVER enters `_decl.*` payloads (extend
   `test_document.py` `test_store_and_path_never_enter_documents`' assertion).
4. **`engine/arrival_registry.py`**: `BackendRegistry.register/open` →
   `(ArrivalLedger, ArrivalQuery)`; `descriptor_for(ast, vertex_path)` with the three
   ruled arms — explicit (wins, NO suffix cross-check, unknown name → typed
   `UnknownBackend` naming registered adapters), inferred-arrival transitional
   (synthesizes backend="file"; carries its slice-5 deletion marker in a comment),
   jsonl/sqlite → None (never route through the registry). Adapters imported lazily
   inside their opener. Registers under Rule 18 `_SCAN_TARGETS` (the WP1 ratchet
   forces this — it goes green when you register).
5. **Parity probe** (§D.4 exit 3): over every `.vertex` in the repo — arrival-canonical
   stores: registry ledger names the same artifact `open_canonical_store` opens;
   jsonl/sqlite: `descriptor_for` returns None and resolution is byte-identical.

## Non-goals

No consumer rewiring (SD-7): nothing starts CALLING the registry in production paths —
this WP builds and proves it. `residence.py` diff-empty. No `role`/`lineage` properties
(deferred to slice 5's adopt). No child-block grammar (reserved). No admission/merge
(WP3), no replicate/export (WP2).

## Oracle (the gate re-runs from scratch)

1. Parser tests: both forms accepted (bare store, store+backend); unknown property
   refused; child block refused; empty backend refused. Mutation demo: revert the
   unknown-prop refusal → the typo test fails; restore, diff clean.
2. Round-trip: a backend-declared vertex survives vertex_to_documents →
   documents_to_vertex with the arm INTACT; backend name absent from genesis payload
   blob. Mutation demo: drop the threading → round-trip test fails.
3. Parity probe green over every repo `.vertex`.
4. `residence.py` diff-empty; `test_residence.py` green unmodified.
5. Rule 18 green (registry registered; WP1 ratchet satisfied). Lang + engine suites
   green; counts reconciled, every delta accounted.
6. `git ls-files` clean on all changes.

## Mechanics

- Worktree: `git -C /Users/kaygee/Code/loops worktree add ~/Code/loops-s2wp4 -b slice2/wp4-kdl-registry 0d38c969`
  (branch off the wave branch tip in your launch message; step 0 verify merge-base).
- Report AS YOU GO: `docs/scratch/arrival-break/slice2-wp4-report.md` on your branch.
  Loops emissions from MAIN checkout cwd, payload
  `agent=s2wp4-impl slice=2 wp=4 role=implementer`; facts only; never stage `.loops/`.
- Commits conventional, trailer:
  `Claude-Session: https://claude.ai/code/session_01JpCUT3bF3dukDk5xjDejRM`
- Finish: SendMessage to parent — tip, files, counts with deltas, mutation results,
  design choices one line each, deviations.

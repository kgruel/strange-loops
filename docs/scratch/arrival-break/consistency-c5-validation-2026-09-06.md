# C5 independent validation — Arrival loop/vertex name identity

Date: 2026-09-06. This is a read-only source audit of the C5/D4 decision. The
audit began before the owner changes landed; the current implementation is
also described below so the acceptance boundary is reviewable.

## Final validation

Final frozen-tree checks, run from the owning package directories or repository
root as shown, were green:

- `cd libs/engine && uv run pytest -q` — **2,562 passed, 1 skipped** in 73.34s.
- `cd libs/sdk && uv run pytest -q` — **540 passed** in 33.88s.
- `uv run pytest tests/architecture -q` — **101 passed** in 8.48s.
- Engine scoped Ruff from `libs/engine` over the four changed engine sources
  and three changed engine tests — **clean**.
- SDK scoped Ruff from `libs/sdk` over the two changed SDK sources and four
  changed SDK tests — **clean**.

After the final preview-error taxonomy correction in `sdk/kind.py` and its
focused SDK assertion, the follow-up checks remained green:

- `cd libs/sdk && uv run pytest -q` — **540 passed** in 22.70s.
- `uv run pytest tests/architecture -q` — **101 passed** in 7.05s.
- `cd libs/sdk && uv run ruff check src/sdk/kind.py tests/test_arrival_declarations.py`
  — **clean**.

The raw transcripts are in
`/tmp/loops-arrival-c5-2026-09-06/{engine-full,sdk-full,architecture-full,ruff-engine,ruff-sdk}.txt`;
follow-up transcripts are `sdk-reviewed-final.txt`,
`architecture-reviewed-final.txt`, and `ruff-sdk-reviewed-final.txt`.
The original start scope contained six production Python files, seven test
Python files, and `libs/sdk/README.md`. Those 14 hashes were stable through
the initial full validation. Root then made the stated preview correction,
changing only `sdk/kind.py` and `tests/test_arrival_declarations.py`; the
follow-up hash and final 14-file manifest capture that intentional delta. The
hash manifests are
`/tmp/loops-arrival-c5-2026-09-06/{sha256-start,scope-hashes-end,final14-hashes}.txt`.
The final preview correction's hashes are in
`followup-changed-hashes.txt`.
The parent edited the consistency matrix during validation; that documentation
change is outside the 14-file implementation/test hash scope and did not alter
the tested sources.

## Contract and construction call graph

The current wire shape gives a tick a `name` and `origin`, but no durable role
(`loop` versus `vertex`). D4 therefore reserves the vertex name from every
loop name in the supported Arrival runtime and in proposed declarations. The
restriction is about interpretation; it does not make an ambiguous existing
log unreadable as evidence.

The supported Arrival runtime is constructed through
`engine.runtime_write.capture_runtime` (`runtime_write.py:959`), which opens
the registered descriptor, opens a CURRENT snapshot, and calls
`_build_effective_arrival_candidate` (`runtime_write.py:722`). That helper
reconstructs the declaration from bounded `_decl` documents, reattaches only
locator ingress, compiles sources/specs, calls `materialize_vertex`, and then
hydrates facts and ticks (`runtime_write.py:741-782`). Source capture then
calls `plan_pending_boundaries` on a detached candidate (`runtime_write.py:992-1000`).
`prepare_ordinary_write`, `prepare_batch_write`, and
`arrival_sources.prepare_source_invocation` all inherit this path. The guard
must run before planning/interpretation, against the effective declaration,
and again after source/template expansion because `materialize_vertex`
unconditionally adds a `cite` loop when one is absent (`compiler.py:1038-1058`).
Thus a vertex named `cite` can create a collision that is not visible in the
declared `loops` block.

The concrete ambiguity is present today. `Vertex.register_loop` accepts a loop
whose name equals `Vertex._name` (`vertex.py:425-447`). In
`hydrate_snapshot`, an owned tick first dispatches to `self._loops[tick.name]`
and then independently treats `tick.name == self._name` as the vertex period
edge (`vertex.py:807-820`). This lets a same-named passive/reset loop be reset
by a vertex tick, and lets a loop tick advance the vertex period. Count
bookkeeping also keys `ticked_loops` by that same name (`vertex.py:835-846`).
`plan_pending_boundaries` similarly keys its closing edges by tick name and
uses the vertex name for vertex consumption (`vertex.py:1288-1310`), so a
foreign interpretation cannot be repaired by an origin-only check. The
legacy `replay` path also recovers vertex period from `last_tick_ts(self._name)`
(`vertex.py:1139-1152`); it must remain legacy behavior rather than receive a
supported-Arrival guard by modifying the generic `Vertex` API.

Declaration preparation (`arrival_declarations.prepare_declaration_edit`,
`arrival_declarations.py:798-925`) parses and semantically validates proposed
text, checks residence, and compares the current effective documents. Its
proposed AST must pass the same collision predicate before signing or applying.
`arrival_initialization._validate_declaration` (`arrival_initialization.py:458-490`)
already validates the parsed declaration before durable intent/mint and must
use the predicate there too. SDK convenience kind/grant/revoke operations
route through `_edit_arrival_declaration` (`sdk/declare.py:186-235`) and need
the same preparation guard; they cannot validate only the local cache when
the adopted effective declaration differs.

The validator must inspect `effective.name` and the final loop/spec names, not
the mutable locator file. `effective_declaration_from_documents` explicitly
uses bounded documents for structure and locator data only for residence and
source ingress (`engine/declaration.py:897-923`). Compiling source files just
to perform declaration-preparation validation would introduce source I/O and
missing-file failures before the operation has a reason to execute; the
preflight guard should cover declared/effective names, while the runtime
candidate guard covers expanded specs.

## Evidence-read and compatibility boundaries

`arrival_consumer.open_read` opens custody and a bounded snapshot, but does
not materialize a runtime (`arrival_consumer.py:120-190`). The following SDK
Arrival operations are evidence reads and should continue to expose an
ambiguous historical log: `read_summary`, `read_facts`, `read_ticks`,
`read_fact_by_id`, `resolve_entity`, and `read_timeline`. They call
`_open_arrival_read` and snapshot methods (`sdk/read.py:95-145`,
`read.py:548-590`, `714-850`, `1069-1125`, `1356-1418`, `1471-1535`).
`inspect_declaration` likewise reports the effective declaration and local
drift from the bounded read (`sdk/declare.py:669-731`), so it must not turn
the report into an execution refusal. `arrival_transfer.open_export` only
verifies/captures an exact prefix and does not require a projection
(`arrival_transfer.py:99-125`); export must remain available.

`read_state` compiles the effective declaration and replays only fact payloads
through specs (`sdk/read.py:949-1017`); it never materializes/hydrates a
`Vertex` or interprets ticks. It therefore does not cross the C5 ambiguity seam
and should remain available for evidence-derived state. Search similarly
derives fields from the effective declaration but does not interpret boundary
ticks (`sdk/read.py:250-283`). Aggregate fold paths should be checked
individually, since they may compile member declarations, but the guard must
not be applied broadly at `open_read`, or raw facts/ticks/export and inspection
would be lost. Legacy `Vertex` replay and legacy storage readers must remain
callable for compatibility.

## Current implementation review

The owner added `validate_arrival_runtime_identity` in
`engine/declaration.py:851-870`. It is called by proposed declaration prep,
initialization preflight, effective Arrival candidate construction before and
after compilation, and the direct ordinary/batch planners. This covers the
required effective-AST, implicit-`cite`, and detached-candidate seams while
leaving generic `materialize_vertex`, `register_loop`, and legacy replay
unchanged. SDK Arrival initialization also rejects the generated `item`/`cite`
collisions before custody setup, and SDK convenience kind operations route to
the signed declaration preparation path with the cache-basis guard.

The focused tests now cover passive, `after`, `every`, and `when` same-name
loops, implicit `cite`, a template-generated spec, direct planning before a
signer call, proposed declaration zero-open refusal, and initializer refusal
before intent/mint (`test_runtime_write.py:420-462`,
`test_arrival_declaration_custody.py:271-303`,
`test_arrival_initialization.py:125-170`). The remaining acceptance question
is boundary placement in any newly added caller: a future Arrival constructor
must invoke the helper before hydration/planning, and any new compiler-added
loop must be checked after expansion. No production bypass was found in the
current supported write/source call graph after these call sites were added.

## Acceptance checks and concrete risks

The implementation should have one shared helper with a typed supported-Arrival
refusal and explicit call sites for: effective candidate before compile,
expanded candidate/specs after implicit additions, declaration preparation,
and initialization before intent/mint. It should cover passive, count/reset,
loop-boundary, and vertex-boundary forms with a single name-equality rule.
Tests should establish that a same-named proposed declaration performs zero
signing/append/cache mutation; an adopted same-named declaration refuses
runtime state/write preparation while `read_facts`, `read_ticks`, fact lookup,
inspection, timeline, and export still succeed; and a vertex named `cite`
refuses after implicit-cite expansion. A legacy `Vertex` with the same names
should retain its existing behavior. Also verify a non-collision declaration
with an unrelated foreign-origin tick remains evidence-visible and does not
become a collision refusal: C5 is a local declaration identity gate, while
origin ownership remains the boundary-consumption rule.

No dynamic filesystem/store fixture was opened by this audit. The focused tests
listed above are owner-provided evidence, not tests authored by this validator;
the final package and architecture checks above are the independent validation
run. Historical continuity and role interpretation for already-recorded
ambiguous ticks remain D5/C6 design questions; C5 correctly refuses new
supported execution while retaining evidence access.

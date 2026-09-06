# SDK Arrival reads — Fable adversarial review

Date: 2026-09-05  
Scope: `libs/sdk` descriptor-first reads, result models, target resolution,
documentation, and tests  
Reviewer: Claude Fable 5.1, static packets, tools disabled

## Invocation and evidence

Each review ran with:

```text
claude -p --safe-mode --model 'claude-fable-5-1[1m]' \
  --no-session-persistence --tools '' --output-format json
```

The final packet contains the owned diff, the complete new Arrival SDK test
file, FileQuery source, final target/type sources, root decisions, and prior
review disposition. Exact artifacts are outside the repository:

- `/tmp/loops-arrival-review/sdk-read-prompt.txt`
- `/tmp/loops-arrival-review/sdk-read-result-round1.json`
- `/tmp/loops-arrival-review/sdk-read-result-round2.json`
- `/tmp/loops-arrival-review/sdk-read-result.json`
- `/tmp/loops-arrival-review/sdk-read-stderr.txt`

The final result reports `claude-fable-5-1` as the substantive model with a
1,000,000-token context window, 2,100 thinking tokens, 3,923 output tokens,
64,800 cache-creation input tokens, and 3,305 cache-read input tokens. It also
reports a 13-token `claude-haiku-4-5` routing/classification call. Total
duration was 48,679 ms. No web searches or tools were used.

## Verdict

The initial review returned **request changes**, led by a protocol-backed
continuation defect. The post-fix review and the full-test-file supplement both
returned **approve**. The supplement found no issue above LOW and confirmed all
claimed regression coverage directly from source.

## Findings and dispositions

1. **High — a resumed fact page queried declarations with a different request.
   Fixed.** A continuation-bound snapshot accepts only its original
   `FactRequest`. `read_facts` now resolves the declaration only on the first
   page. The fake adapter binds the continuation request and raises
   `InvalidContinuation` on any mismatch; the two-page regression passes.

2. **Medium — `as_dict()` exposed an unprotected continuation structure.
   Fixed.** `FactPageResult.as_dict()` redacts engine `Continuation` values and
   emits `has_continuation`; the live object remains available for in-process
   resume. Tests and the README state this boundary.

3. **Medium — every declaration check scanned all facts. Fixed within the
   required declaration semantics.** Summary, first-page facts, ticks, and
   lookup request only the `_decl` subtree. State alone requests the complete
   bounded prefix because it must fold user facts. The supplement verified
   that FileQuery implements `FactRequest.kind` with the dotted subtree
   predicate.

4. **Medium — descriptor preclassification leaked parser errors. Fixed.** A
   malformed vertex no longer escapes from the descriptor probe. The public
   Arrival target resolver reports it in the SDK target taxonomy; legacy
   reader behavior is unchanged.

5. **Low — role wording advertised an unsupported Archive choice. Fixed.** The
   SDK now requires a generic explicit store role and leaves the registry to
   enforce operation/profile compatibility.

6. **Low — aggregate member refusal inspected direct children only. Fixed.**
   The guard recursively walks combine/discover members with cycle protection,
   handles vertex suffix case consistently, and refuses a nested
   descriptor-backed descendant before legacy store resolution.

7. **Low — stale wrapper docstrings and item-shape documentation. Fixed.** Tick
   and lookup docstrings name their result wrappers. The README explains that
   Arrival item dictionaries include receipt coordinates while the enclosing
   result's `read_path`, `basis`, and `store` identify the contract boundary.

8. **Low — engine/declaration refusals were undocumented. Fixed.** The README
   now states that descriptor-first reads preserve evidence-bearing engine
   contract and declaration-resolution refusals.

The final review retained only preferences: pre-validating changed continuation
arguments before the adapter does and improving a malformed-file error message.
Its internal fact-lookup observation exposed a same-function inconsistency and
was fixed after the supplement: Arrival lookup now excludes `_decl.*` by
default, like the legacy reader, with focused coverage. It speculated
that `resolve_vertex` might throw during the aggregate walk, but the supplied
source shows it is a pure path resolver. These do not violate the ratified
contract and were not used to grow the protocol. The fake snapshot's kind
filter was tightened after the supplement so its `_decl` behavior also matches
the verified FileQuery subtree semantics.

## Validation

- SDK suite: **350 passed**
- Final focused Arrival SDK test file: **21 passed**
- Engine Arrival consumer + contract + registry: **81 passed**
- Architecture: **101 passed**
- SDK Ruff: passed
- `ty check` on changed SDK source modules: passed
- `git diff --check` on SDK scope: passed

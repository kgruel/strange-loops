# C7 continuation: aggregate descriptor resolution

Status: implemented and accepted after Fable-low review. Checkpointed with
this report, following C7 checkpoint `f5563d2f` on
`arrival/finish`. The user requested this continuation before compaction for
D0 → D2. Terra implements, Luna independently audits and validates, and root
owns scope and Fable-low review triage.

## Contract and change

Summary, state and timeline already capture an explicit root descriptor and
choose execution topology from its bounded effective declaration. Their
`_aggregate_aware_arrival_descriptor` bridge previously caught the default
single-store aggregate refusal and reparsed the local file. Replacing the
file between those parses could switch the selected descriptor or fail a
read that had already parsed a valid root.

The bridge now delegates to `_arrival_descriptor(target, allow_aggregate=True)`.
This reuses C7's retained parsed-root logic and explicit-role checks. The
original parsed descriptor remains the selected residence if the local file
is subsequently replaced. Default single-store callers still refuse local
aggregate descriptors. The result models, effective declaration selection,
registry routing and custody/projection requirements do not change.

This is a fix to the descriptor bridge, not a claim that entire aggregate
planning is one filesystem transaction. The earlier storeless-descendant
predicate and later aggregate definition/member captures remain distinct
observations. Recursive storeless planning, credential bindings and C9 remain
outside this continuation.

## Acceptance and review

Public summary/state/timeline regression tests replace the locator after the
target parser returns its first AST. Reads must retain the original descriptor
and captured effective declaration. Existing aggregate, registry injection,
read and target tests cover the unchanged surrounding contracts.

All validation invocations must isolate state/config/Loops home at process
level, as well as keeping the new module's autouse state fixture. The C7 test
isolation fix covered its new module; that alone does not establish isolation
for every inherited SDK test. This continuation explicitly isolates the full
suite rather than relying on individual historical fixtures.

Validation: **562 SDK tests**, **101 architecture checks**, and scoped Ruff
pass. A later test-only refinement makes the replacement a valid aggregate
descriptor, and all 3 refined public regressions pass. The full suite precedes
that fixture refinement; production is unchanged. See the
[validation report](consistency-c7-followup-validation-2026-09-06.md).

Root also loaded only the committed pre-fix resolver function into memory and
ran those same refined regressions: all **3 failed**, attempting to open the
replacement `missing.arrival` residence. The current resolver passes all 3.
No source file was reverted for this probe. Its script and observed failures
are retained with review evidence.

Fable-low returned **ACCEPT**, no blockers. Root's
[triage](reviews/consistency-c7-followup-2026-09-06/primary-triage.md) corrects an
over-broad reviewer statement about downstream local file reads and preserves
the selected bridge-only guarantee. No post-review source/test edits were needed.
C7's frozen review artifacts remain untouched.

The continuation is checkpointed with this report; nothing pushed. D0 credential
request design, then D2 persisted bindings/compatibility, remains the next task
after the user's planned compaction. No D0/D2 implementation has begun.

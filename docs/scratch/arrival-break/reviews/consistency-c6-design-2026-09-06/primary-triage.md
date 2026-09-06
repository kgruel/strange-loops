# C6 design review — primary triage

Status: design accepted by root after two Fable-high reviews and factual
verification. No C6 production/test changes preceded design triage.
Baseline `ef8b21b2`.

The frozen initial packet is 189,575 bytes, SHA-256
`628adc28379988d79bac226df15bf108a408b5246b7a079595cef553af068597`.
Runner exit 0; canonical Fable 5.1 output verified, 21,176 output tokens of
which 17,768 were thinking. A 16-token Haiku CLI helper was also reported.
Initial source drift was empty. Raw findings remain unchanged.

Fable recommended **REVISE**, while endorsing inherit-by-name as a sound
implementable policy. Root retains that recommendation; the optional user
preference question had not been answered at initial review. The revised root
design is authoritative where original supporting notes offered alternatives.

## Finding disposition

| Finding | Root judgment and revision |
| --- | --- |
| B1, consumer-scoped historical vertex ambiguity | Accepted. Refuse an ambiguous vertex-name tick only when the target declares a vertex boundary that consumes its period evidence. A corrected target without that consumer can run; proposing it again refuses. Current C5 still excludes a loop with the vertex name. |
| B2, mixed tick/declaration rows at one ordinal | Counterexample rejected as a legal wire shape; defensive rule accepted. Wire batches expand fact rows only. A CAS list may contain facts and ticks, but each draft gets a distinct record ordinal. A query claiming an owned tick and declaration fact at one ordinal contradicts the profile and refuses explicitly. |
| B3, runtime refusal evidence | Accepted in substance. Add a narrow runtime refusal subtype retaining actual basis, declaration, issue, and existing C2 scalar coordinates/effect proof. Declaration preparation can use explicit exception chaining; a new generic cause parameter is unnecessary because C2 already walks `__cause__`. |
| B4, count recovery | Accepted. The design now specifies ticked count K >= new M firing on next routed ingress; unticked repeating recovery modulo M; unticked one-shot exhaustion from old facts; and every/after transitions. Tests must verify these existing semantics rather than invent retroactive firings. |
| B5, historical parameter pins | Accepted correction. Matching historical hash-pinned bytes prove rows. A shared caller-side evidence collector passes verified ordered parameter rows to the pure classifier for runtime, preparation and preview. Missing/mismatched/unpinned bytes and env-derived names remain unknown. Hash and parse the same read; share the existing compiler parser. |

## Source checks beyond the initial packet

- `arrival_body.py:179-239,270-294` defines fact-only wire batches and their
  expansion. `ArrivalLog.append_marked_many` assigns consecutive outer ordinals
  across draft records. The review's reference to the runtime `logical` list
  confuses one CAS with one record. No mixed-row format is added by C6.
- `_vertex_period_start` reads in supported detached Arrival ingress/pending
  paths are gated by a declared vertex boundary. The legacy
  `_evaluate_vertex_only_boundaries` caller is itself gated, and attached legacy
  `evaluate_boundaries` remains out of this supported capture contract.
- `FileQuerySnapshot.ticks` uses the captured ordinal bound and SQL timestamp
  inequalities. An explicit `since=-inf` selects the full finite timestamp
  range. Keep separate continuity and existing runtime tick selections.
- `FactRequest(kind="_decl")` uses `kind_subtree_predicate`; it selects the
  declaration subtree, not only a literal `_decl` kind.
- C2 `_causal_exception` selects an explicit `.cause` or `__cause__`, and
  `_identity_details` retains actual heads and scalar tick/fact coordinates.
  No new error-wire schema or fabricated Commit is necessary.

The revised design also aligns the target input to documents, specifies `$NAME`
and `$$` behavior, preserves implicit `cite`, applies the history check to no-op
proposals, and uses provable generated names for C5 during semantic preview and
declaration preparation. Credential callback loading may precede capture;
signer invocation does not precede the continuity gate.

Production/test scope remains unchanged throughout design review. Design and
native-note revisions after the first packet are intentional and will be frozen
in the follow-up packet; the initial packet and raw findings are not rewritten.

## Follow-up and final design decision

The high-effort follow-up packet is 162,710 bytes, SHA-256
`f03a1ca5123fc1b49282c29f8c11cc5e83171ec229954d2249a403a413c94269`.
It resolved B1–B4 and the initial algorithm questions. Its raw verdict was
REVISE based on one new must-fix: it claimed current runtime compiles parameter
files without first verifying their pins. Root, Sol, and Luna independently
confirmed that premise is false. `runtime_write.py:742` calls
`effective_declaration_from_documents` with default `verify_pins=True`;
`declaration.py:944-947` invokes the document pin verifier, including the
`from.params_sha256` check at `:913-916`, before compilation.

The supporting call chain was omitted from the follow-up packet. Root accepts
responsibility for that evidence gap; it does not justify implementing a
duplicate gate. The missing source is retained in
[pin-gate-supporting-source.txt](followup/pin-gate-supporting-source.txt).
Luna ran four focused existing pin/resolver tests (two commands, two passing
tests each) and a disposable exact params-branch probe: matching bytes pass,
drift raises `SourceDrift`. Raw logs/script/hashes are retained in `followup/`.
Sol independently reported five overlapping focused tests and the same direct
branch result; those counts are not additive.

The remaining note inconsistencies were reconciled: every relevant tick is
checked, boundary disable with the runtime name retained inherits, the defensive
shape check targets owned tick plus self-lineage declaration at one ordinal,
pre-genesis consumers are explicit, and declaration conflicts are wrapped before
the generic basis handler. Runtime compiled-name agreement is explicitly
bidirectional so removal of a provable name also refuses. These clarify the
already selected contract rather than adopting a new continuity policy.

Root accepts the design and starts implementation. This is **primary acceptance
after reviewed corrections and factual rejection**, not a claim that Fable
returned ACCEPT. No third design review is needed for a disproved missing-gate
claim. The implementation will receive its own established low-effort review.
The optional user preference remains unanswered; inherit-by-name is the stated
recommended assumption, endorsed in both external reviews.

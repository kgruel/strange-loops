# D0→D2 identity validation plan — 2026-09-06

This is an independent validation plan for the next credential-binding slice.
It does not ratify a wire migration or a filesystem layout. The authoritative
constraints are [identity decisions](identity-decisions-2026-09-06.md), the
[identity audit](consistency-audit-identity-2026-09-06.md), and the Arrival
wire/backend contracts.

## Executed validation — initial implementation freeze

The matrix below began as an acceptance plan. The measured runs are:

| Suite | Result | Raw log in review validation evidence |
| --- | --- | --- |
| Engine | 2,611 passed, 1 skipped / 70.50s | engine-full.txt |
| SDK, final | 578 passed / 23.97s | sdk-full-final.txt |
| Custody | 67 passed / 1.54s | custody-full.txt |
| Sign | 40 passed / 5.13s | sign-full.txt |
| Architecture | 101 passed / 7.57s | architecture.txt |
| Changed Python Ruff | Passed | ruff-final.txt |
| Diff whitespace | Passed | diff-check.txt |

Root used process-level isolated state/config/Loops roots per suite, all beneath
`/tmp/loops-arrival-d0-d2-2026-09-06/validation`. Agent focused checks also used
isolated roots. No test intentionally addressed real credentials or live stores.

New public-flow tests in `test_arrival_mapped_credentials.py` passed 12 cases:
domain checks; initialization with a distinct observer; relocation; two-author
packed batches; receipt signatures; source-tier resolution and collector error
evidence; preview non-persistence; explicit grants; wrong public-key refusal;
relabeled bootstrap evidence; legacy refusal; and missing-reference refusal.
Some tests cover multiple assertions. These do not exhaust every hypothetical
case in the original matrix below.

Root's seven independent recovery tests initially reproduced draft failures
and then passed. Four malformed-public-evidence tests ensure refusal output is
JSON-serializable. Existing engine tests were extended for mapped author and
receipt policy, captured contexts, declaration signing, and legacy refusal.

The first full SDK run had 40 failures and 7 setup errors from one omitted
keyword argument at five SDK kind guard call sites; all were resolved before
the final full run. Combined custody/sign importlib collection caused spawned
workers to fail importing their test module; separate normal package collection
passed. Both initial failures remain in the raw evidence.

Two engine test formatting changes followed its full run; production was
unchanged. The final SDK run includes the later SDK guard and serialization
fixes. Hash records distinguish initial validation from the review freeze.
The review was pending at this initial freeze; final closure is recorded below.

## Final recovery validation and review closure

The latest full SDK run passed **578 tests / 22.17s** (`sdk-after-recovery.txt`).
After the final fresh-token correction, Terra’s full custody run passed **76**
tests and its focused provider/recovery run passed **26** (captured in tool
results and the final review handoff; no separate full-run raw log was saved).
The SDK run predates only that last custody branch correction. Engine, signing,
and architecture production remain unchanged from the runs above. Final scoped
Ruff passed (`ruff-closeout.txt`). Source hashes record the final code state.

Root retained executable evidence for the published-intent mismatch and the
pending-before-index token failure, then their corrected results. The final
current-source probe refuses original-token create/recover and fresh-token
create; it is current passing evidence, not an original red run.

The first broad Fable-low implementation **ACCEPT** was overridden by those two
root counterexamples. The next focused review returned **REVISE** for the fresh-
token bypass. The final focused review returned **ACCEPT**, with root triage
**ACCEPT**, no remaining blockers and no reviewed source drift. See
[final primary triage](reviews/consistency-d0-d2-final-2026-09-06/primary-triage.md).
The following matrix and proposed split are the historical acceptance plan;
measured coverage and its limits are the executed results above.

## Directory durability follow-up validation

Root’s final directory review found missing parent-entry fsync, then a second
probe showed retry reporting completion after a binding link whose directory
sync had failed. Both are corrected. The latest full isolated custody suite
passed **80 tests / 0.48s**; raw output and before/after probe evidence are in the
[durability review artifacts](reviews/consistency-d0-d2-durability-2026-09-06/validation-evidence/).
The four new regressions check directory sync ordering and interrupted retries.
They do not simulate physical power loss. Final scoped Ruff passed. The SDK
578-test run predates these custody-only corrections; unchanged engine, signing,
and architecture retain their earlier results. Focused Fable-low review is
pending at this freeze.

## Final acceptance

The focused durability review returned REVISE for one imported-key recovery
branch that skipped syncing an already visible copied public file. Its correction
and realistic interrupted-import regression passed the final isolated full custody
suite: **81 passed / 0.55s**. Final scoped Ruff passed. Raw logs and final hashes
are retained with the [final review](reviews/consistency-d0-d2-durability-followup-2026-09-06/primary-triage.md),
which returned Fable-low **ACCEPT**, primary **ACCEPT**, with no source drift and
no remaining blockers. This closes the pending freezes described above; their
measured counts and historical verdicts remain unchanged.

## Contract under test

D0 separates four values that must not be inferred from one another:

1. the exact protocol observer label;
2. the provider's explicit custody namespace and opaque key reference;
3. the signing domain (FACT, ARRIVAL, or tick); and
4. the verification context, including lineage and the captured successor
   coordinate at which a key was valid.

D2 persists the provider's mapping from exact observer identity to opaque key
references. It keeps the existing flat self-key and nested observer behavior
as compatibility inputs, while refusing ambiguous aliases, conflicting
public material, unsafe path components, and silent winner selection. A
filename, vertex stem, descriptor location, lineage, or equal observer label
across lineages is not a key-history proof.

## Adversarial matrix

### Request and domain separation (D0)

- A fact, batch, and declaration edit request credentials with explicit
  observer/domain context. A provider must never substitute the vertex name,
  boundary name, founding observer, or location for the requested observer.
  An inner tick commitment uses the TICK domain and has no author label; its
  receipt-signing capability follows the established any-key policy. The
  outer Arrival envelope is unsigned and carries the physical log custodian.
- `WriteCredentials` must preserve independent FACT, ARRIVAL, and tick
  callbacks. Missing one callback remains the operation's existing unsigned
  posture where allowed; another callback must not be used as a fallback.
  Verify each signature under its own domain and assert cross-domain
  verification fails.
- A provider is queried fresh per operation. Reads, previews, verification,
  signer loading, and failed preflight must not generate a private key or
  publish a binding. A failed signer/public-key relationship must refuse
  before intent, mint, or append.
- A key introduced at captured H is valid for a successor record at H+1, not
  retroactively for H. Test valid and invalid introduction coordinates,
  unknown observer, wrong lineage, and a signer whose bytes do not match the
  presented public evidence. Preserve the actual captured H and cause in the
  typed refusal.
- A tick's inner TICK signer and outer Arrival custodian label remain
  distinct. Test a tick signed by a non-genesis key and confirm the outer
  envelope still follows the established custodian rule. For facts, test an
  author different from the physical genesis observer. Equal labels in
  separate lineages must not be reported as globally authenticated identity.

### Mapping and compatibility (D2)

- Existing flat `keys/ed25519.key` remains the self-observer compatibility
  key. Existing exact nested `keys/<observer>/` keys remain usable. Moving or
  renaming the `.vertex` file must not silently select a new key for the same
  explicit observer when a persisted binding exists.
- Exact nested labels, slash namespaces, case variants, Unicode, empty
  components, dot/parent components, reserved key filenames, symlinks, and
  regular-file path components must be tested. Preserve the current refusal
  policy; never borrow a case-folded or traversal-equivalent key.
- A mapping whose observer/namespace/reference is malformed, whose public
  material disagrees with the key, or whose target key is missing must refuse
  without overwriting existing bytes, minting a replacement, or choosing a
  newer arbitrary row. A mapping for one lineage is not silently reused as
  proof for another lineage unless the provider explicitly declares that
  namespace reuse and the operation still verifies lineage key history.
- Concurrent creators for the same exact binding must converge on one
  complete winner or return a typed conflict. They must not publish a partial
  mapping, two private keys, or a mapping pointing at the losing key. Inject
  interruption after key creation, after mapping temp write, and after rename;
  recovery must retain enough evidence to reconcile without generating a new
  identity.
- A provider configured with an unsupported key root must fail explicitly
  before signer lookup. The current `CustodyCredentialProvider(key_dir=...)`
  refusal is the compatibility baseline until an explicit provider/key-locator
  design is implemented; callers must not believe the argument was honored.

### Operation and error compatibility

- Existing unsigned/pre-signature behavior remains legal where the operation
  permits it. A missing local key on a read or signer load must not mint one.
- Precommit input/configuration errors retain zero-mutation evidence. An
  append after credentials are acquired retains stable fact/tick IDs, captured
  head, and the proper committed, unwitnessed, projection-failed, or unknown
  outcome. Credential lookup failure must not be mislabeled append-unknown.
- Public error/outcome serialization must expose enough namespace, observer,
  domain, key-reference/public-evidence status, captured verification
  coordinate, and mutation phase to explain a refusal or uncertain result,
  without leaking private key bytes or reducing a committed outcome to a
  generic refusal. Success DTOs need only expose the identity evidence their
  operation contract promises; this plan does not require every result to
  repeat provider-internal references.
- Registration and custom-provider paths must preserve opaque backend
  locations and the caller's registry. Credential configuration must not
  derive identity from an adapter DSN or fall back to the built-in provider.

## Existing evidence to extend

The current baseline already covers domain-separated custody signers and
flat/nested compatibility in `libs/custody/tests/test_signing.py`, including
alias, symlink, traversal, ambiguity, missing-load, and cross-domain cases.
`libs/sdk/tests/test_emit.py` covers operation-fresh `WriteCredentials`,
unsigned behavior, and the explicit refusal of the ineffective `key_dir`
override. `libs/sdk/tests/test_arrival_init.py` covers injected separate
fact/Arrival signers, wrong-domain and key mismatch preflight, partial custom
credentials, and recovery without generating a replacement key. These tests
are the compatibility floor; D0/D2 additions should prove persisted binding
selection and concurrency rather than mirror helper internals.

## Proposed focused test split (pending API freeze)

Do not add these files until the provider request and binding result types are
settled. The likely ownership split is:

- `libs/custody/tests/test_binding.py`: persisted observer-to-opaque-reference
  selection, flat/nested compatibility, exact case/slash/Unicode labels,
  traversal/symlink/regular-file rejection, mismatched public material,
  concurrent creators, and interruption at key or mapping publication. Each
  case should assert prior bytes survive and that a loser cannot replace a
  complete winner.
- `libs/engine/tests/test_arrival_credentials.py`: engine-facing request
  context and verification only. Cover separate FACT/ARRIVAL/TICK domains,
  TICK's authorless inner commitment plus unsigned outer custodian envelope,
  key validity at H versus H+1, wrong lineage/unknown author, and the
  distinction between credential/preflight refusal and append-unknown. Use
  injected callbacks or signed temporary records; do not import custody
  layout helpers into the engine package.
- `libs/sdk/tests/test_arrival_mapped_credentials.py` (with compatibility
  assertions remaining in `test_emit.py` and `test_arrival_init.py`): public
  provider registration,
  moved vertex residence, opaque backend namespace collision refusal, fresh
  provider calls, no key generation on reads/previews, unsupported key-root
  override, and JSON-safe refusal/uncertain-result evidence. A success DTO
  should assert only the identity fields promised by its operation contract.

Sol's provisional neutral seam gives these cases concrete request points:
`SigningDomain`, `CredentialRequest(namespace, observer, domain)`, and
`CredentialBinding(request, key_ref, public_key, sign_digest)`, plus provider
namespace/receipt-observer/resolve/verifier operations. The tests should use
that seam when frozen rather than reach into custody filenames. For a TICK
request, the inner signature is TICK-domain evidence without an author label;
the outer receipt remains unsigned physical-custodian evidence. The request
shape must not turn either into a FACT-author assertion.

The minimum cross-operation acceptance sequence is: create an isolated real
lineage; bind two exact observers; introduce one observer at a known H; sign a
fact and a TICK-domain inner record with their required callbacks; verify the
unsigned outer envelope's custodian; then move the vertex residence and repeat
the lookup. Separate negative cases must prove that a FACT callback cannot
stand in for ARRIVAL or TICK, H is not retroactively authorized, an opaque
provider key is not interpreted as a local path, and a failed preflight creates
no key, mapping, intent, or append. These are contract tests, not requirements
to expose provider-internal references on every successful result.

The strongest conformance fixture should create a real temporary lineage,
introduce one or more observer keys at known ordinals, and perform a signed
fact, signed declaration/tick inner record, and Arrival envelope. It should
verify every signature against the historical registry and then repeat after
moving the vertex residence or changing the provider's local path. A separate
fake provider should prove opaque namespaces and collision refusal without
filesystem interpretation.

## Validation protocol and limits

Every test process must set isolated `XDG_STATE_HOME`, `XDG_CONFIG_HOME`, and
`LOOPS_HOME` beneath a disposable task directory. Test setup must assert those
roots before creating keys or opening a store; no test may use the developer's
default custody state. Capture before/after hashes for provider and SDK files,
raw focused/full-suite output, architecture checks, and scoped Ruff.

No test in this plan moves or deletes real keys, rewrites live stores, invents
global identity equivalence, adds revocation semantics, or changes the Arrival
wire profile. Durable alias transfer, cross-lineage identity associations,
and a complete migration from filename lookup remain separate designs. The
first implementation should be accepted only when a failed or interrupted
binding operation leaves an honest typed result and preserves all prior key and
mapping bytes.

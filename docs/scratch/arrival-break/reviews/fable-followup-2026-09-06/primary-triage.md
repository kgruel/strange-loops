> Subsequent remediation: the six behaviors below have been addressed. See
> `../remediation-2026-09-06/primary-triage.md` for final review judgment,
> implementation evidence and remaining scope. This assessment is historical.

# Fable follow-up: primary triage, September 6, 2026

All four requested static reviews completed with `claude-fable-5-1[1m]`,
`--effort low`, tools disabled, and no session persistence. The three unfinished
original stages (verification/pagination, observer guard, export) are now
reviewed, followed by a focused review of the five correctness fixes. The
original ten reviews were not rerun. No reviewer job remains running.

Packets contain current source excerpts with original line numbers. Source and
packet SHA-256 checks passed with no source drift. Fable produced the substantive
review output; the CLI also recorded tiny Haiku helper outputs, not replacement
reviews. Exact model usage is retained. These are static reviews, not reviewer
executed tests. Native Sol/Terra/Luna checks and root reproductions supply the
execution evidence below.

## Remaining findings, after reproduction

| Priority | Finding | Evidence and next decision |
| --- | --- | --- |
| Medium | Observer key directory aliasing on case-insensitive storage | Supported `ensure_signing_key` calls for `Alice` and `alice` return the same public key and same physical file on this macOS filesystem. Exact-string verifier lookup still prevents a signature from passing against a different declared public key. This is silent key selection/identity aliasing, not a demonstrated signature forgery. Choose collision detection or an identity-preserving directory encoding at both mint and load. Do not lowercase observer identities as a shortcut. |
| Medium | Self-observer mint and signing disagree after a rename | Create `keys/new/` while the locator is `old.vertex`, then rename to `new.vertex` and ensure observer `new`. Creation returns a new flat key; fact signing prefers the old nested key. The signature verifies under nested and fails under the returned public key. Decide canonical self-key precedence consistently across mint, fact/arrival signing and legacy flat tick signing; ambiguous existing layouts need explicit treatment. |
| Medium | Prefix lookup excludes valid fact IDs | Real SDK `emit_fact(..., id_override=...)` accepts `aé-tail` and `b~tail`; exact lookup succeeds, prefix `a` or `b` returns none. `arrival_file_backend.py:1127-1129` uses `id < prefix + "~"`. Use a literal prefix predicate that also handles valid `%`, `_`, `[` and other arbitrary ID characters; retain ambiguity checks. |
| Medium, boundary identity decision | An unrelated-origin tick consumes a local same-named boundary | Real initialized Arrival store, public capture/plan/execute/sync and registry append: local `note@batch-target` closes at 4; a valid custodian-signed `note@other` at 10 then suppresses local `seal` at 5. Root controlled variant without the other-origin tick produces the pending `note` close. `vertex.py:1273-1277` keys edges only by name. The behavior is confirmed; define whether boundary identity includes origin and apply it consistently to hydration and planning. Do not change only this dictionary while leaving replay/reset semantics inconsistent. |
| Low | Export source I/O failure is labeled publication failure | A source iterator yielding one chunk then raising `PermissionError` becomes `ExportPublicationError`. No output or temporary artifact remains. This is a phase-attribution gap; `artifact-not-published` is accurate. Contrary to Fable's suggested alternative, raw `OSError` is not normalized to `ArrivalRefusal` today. |
| Low, result semantics | Recovery says `file_written=True` when this call did not rewrite cache | Interrupt apply before intent removal, after successful cache publication. Public recovery succeeds with no Commit, removes intent, preserves cache bytes/inode/mtime, and returns `file_written=True`. Define whether this field reports the recovered operation's state or this invocation's action; use a distinct state/action field or document it clearly rather than implying a fresh write. |

The first three and the reporting observations arose from Fable findings or its
explicit context questions; the cross-origin boundary observation arose from
Luna's independent follow-up. All six behaviors were independently reproduced
by root. Severity is primary judgment, not copied from the reviewer verdict.
No production code changes were made in this review pass.

## Reviewer findings rejected or qualified

- Export 0600 mode is owner read/write, not "owner-read-only". No current
  contract requires group/world-readable artifacts. Reject as a correctness
  finding. Writing directly to the destination would weaken the existing
  atomic/no-replace publication behavior and is not an acceptable remedy.
- Absent projection anchors are `(None, None)` and the shared validator permits
  them. `ArrivalLog.walk` validates grammar/hash, record placement, lineage,
  dense ordinals and previous-hash continuity. Negative ordinals are refused.
  These close the verification/export missing-context questions.
- Ordinary registry open intentionally applies witness/projection gates even
  for verification/export. "Without reading its projection" means no query
  snapshot is used for the verification claim; it does not bypass contradictory
  projection evidence at attested open. Clarify that docstring if needed.
- Registry opens own their resources and do not return shared cached ledgers.
  The SDK passes `opened_root` into an aggregate capture and then consumes that
  capture within its enclosing context. Transfer/borrow ownership deserves a
  docstring, but no actual supported-path use-after-close was demonstrated.
- Builtin absent snapshots have no rows; a fabricated snapshot claiming absence
  while returning rows is nonconforming. Storeless `combine`/`discover` survive
  document round-trip. Restore closes its raw ledger once; the temporary
  attested wrapper delegates to that same handle and owns no extra handle.
- Preparation wraps `ProjectionBehind` / `AtomicLimitExceeded` and retains
  causes. Loss of the outer specific error type is a preexisting secondary
  diagnostic item, not a newly demonstrated write failure.
- Fable's statement that postcommit restore audit failures are necessarily
  "unwitnessed" is too strong: constructing `actual = AttestedLedger(...)` may
  already journal earned observation before the exact row audit. The actual
  Commit is retained in `RestoreForwardIncomplete`; absence of all witness
  evidence is not promised. Its assertion that concurrent watermark clamping
  is unreachable is also not relied on as a contract.

## Validation and scope

| Check | Result |
| --- | --- |
| Root restore + boundary regressions | 29 passed |
| Sol SDK verification + Arrival reads | 25 passed |
| Sol engine Arrival consumers | 19 passed |
| Terra engine transfer + coordinator | 36 passed |
| Terra SDK export | 6 passed |
| Terra custody signing | 27 passed |
| Luna runtime/source/boundary subset | 68 passed (includes 10 focused boundary tests) |
| Root six behavioral reproductions | All reproduced, including origin control |
| Root `git diff --check` | Passed |

Counts overlap and are not summed. The full engine/SDK suites were not rerun
because this pass made no production changes. All probe stores, generated keys
and witness state were disposable. Scripts are retained as `.py.txt` under
`probes/` to avoid accidental test collection. Root observations are preserved
in `root-probe-observations.json`; agent raw outputs are alongside scripts.

The five original failures remain fixed under their regression coverage; the
new origin case expands boundary coverage. This is not blanket acceptance of
Arrival. Earlier secondary findings and the explicit projection preservation/
rebuild design remain separate work. Main checkout is untouched; arrival/finish
implementation changes remain uncommitted, with this pass adding review records.

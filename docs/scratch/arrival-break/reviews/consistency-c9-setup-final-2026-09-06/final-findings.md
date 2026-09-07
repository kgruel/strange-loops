# final — Fable review

Effort: low. Finished: 2026-09-07T03:27:58.663927+00:00.
Packet SHA-256: `8e15169b83e225d34e29a3a901e1b36a12aa814a0341e6a5feb4a58c898626b5`.

Static reviewer output; findings still require primary triage.

**Verdict: REVISE** — one blocker, otherwise the slice matches its claims.

## Blocker

**B1. Custody `TypeError` escapes the conservative incomplete wrapper.**
`libs/sdk/src/sdk/emit.py:238` catches only `(OSError, ValueError)`. Custody raises `TypeError` at `libs/custody/src/custody/binding.py:343` (`_read_json`, non-object JSON record) and `:514` (`_pending_by_token`, pending intent lacking slot identity).

- **Trigger:** any corrupt `pending-v1/*.json` or `intents-v1/*.json` whose top level is a JSON array/scalar. Reachable pre-mutation via `_intent_for` → `_pending_by_token` (`binding.py:593`), and **post-mutation** via `_ensure_token_index` → `_read_json` (`binding.py:531`) after the pending marker has already been published at `:711`.
- **Consequence:** the raw `TypeError` reaches `main.py:511`, `normalize_exception` has no SDK family for it, `_exit_code` returns 70, and the JSON error is the generic fallback with no namespace/observer/token/phase. This contradicts the packet's claim (`consistency-c9-setup…md:47-52`, `sol-audit.txt:6-7`) that failures after entering custody are reported as incomplete/unknown with request coordinates, and in the post-marker case it drops the exact evidence the operator needs to run `credential-recover`.
- **Minimal correction:** change `emit.py:238` to `except (OSError, ValueError, TypeError) as exc:` and add one lifecycle test that plants `[]` in a pending or intents record and asserts `CredentialBindingIncomplete` with `phase="unknown"`, `source_type="TypeError"`, and the request coordinates. Update the doc sentence at `md:47` and the README sentence to say "raw custody OSError/ValueError/TypeError".

## Optional observations (non-blocking)

- **Status-6 for pure precondition mismatches.** `bind_existing_ref` with a wrong expected key or unknown `key_ref` yields exit 6/incomplete although custody fails before any write (`binding.py:1046`). This is documented as deliberate conservatism and tested (`test_credential_lifecycle.py:144-150`); it just means operators will see "reconcile" for what is really a refusal. Acceptable for this slice.
- **Legacy-import absent-candidate recovery is not asserted in this packet.** `binding.py:980-984` raises `BindingRecoveryRequired` for that case, and the docs describe it (`md:56-57`), but no test in the packet exercises it. The custody suite log (31 passed) may cover it; the packet cannot prove that. Worth one SDK-level assertion.
- **Compatibility wording.** `CredentialBindingResult` is a field superset of `BindingCreationResult` (adds `operation`, `schema`). Callers that round-trip via `BindingCreationResult(**asdict(result))` would break. The README already says the concrete type changed, which is honest enough.
- **`recover_binding` raw re-raises.** Custody deliberately re-raises `FileNotFoundError`/`ValueError` from recovery as precommit refusals (`binding.py:1023-1026`); the SDK reclassifies them as incomplete/unknown with `key_ref=None`. Consistent with the stated policy, just note that the conservative path loses the intent's known `key_ref`.
- **Evidence scope confirmed.** The `os._exit(75)` after-mint test, custody-moved-away recovery, refused repeat recovery, and post-recovery signed emit/read/verify are all asserted as claimed in `test_setup_cli.py:124-197`. The mocked delegation tests are correctly labeled as not crash evidence. Wheel evidence covers create/replay/recover/reuse only, matching its stated scope. No private keys or callables appear in serialized output (`types.py:215-216`, `:102-120`).
- **Migration sidecar gap** (`migrate.sidecar.edit_vertex_store_clause` lacking role) is recorded as next work at `md:108-113`, not silently changed. Correct.

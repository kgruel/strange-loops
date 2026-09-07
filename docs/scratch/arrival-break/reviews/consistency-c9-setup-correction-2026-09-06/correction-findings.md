# correction — Fable review

Effort: low. Finished: 2026-09-07T03:33:31.861653+00:00.
Packet SHA-256: `bf12dc18a4508b6db1a34f5fc65197cf4a79780219aa781aabb4865795b82d5d`.

Static reviewer output; findings still require primary triage.

# correction — Fable review

Effort: low. Static reviewer output over the supplied packet; no tools or tests were run by the reviewer.

**Verdict: ACCEPT** — B1 is fixed by the minimal correction; no remaining blocker.

## B1 confirmed fixed

- **Production change is exactly the minimal one.** `libs/sdk/src/sdk/emit.py:238` now reads `except (OSError, ValueError, TypeError) as exc:`. No blanket `Exception` handler, no custody change. Ordering is still correct: the three custody `ValueError` subclasses are caught first (`:209-237`), so they keep their dedicated families. Input-shape validation (`:203-206`) stays ahead of the try, so `SdkValueError` is not reclassified.
- **Pre-mutation path covered.** `test_credential_lifecycle.py:226-256` plants `[]` in a pending record and in the token's intent record. Both reach `_read_json` (`binding.py:342-343`) before `_mutate`'s inner try and now yield `CredentialBindingIncomplete` with `phase="unknown"`, `source_type="TypeError"`, `key_ref=None`, exact coordinates, and unchanged bytes (lock file pre-seeded so the invariance isolates record handling).
- **Post-marker path covered.** `test_credential_lifecycle.py:171-214` parametrizes `TypeError` alongside `OSError` at `_ensure_token_index`, asserts the retained pending marker's exact content, unknown phase, no invented `key_ref`, then same-token `recover_binding` succeeds.
- **Process boundary covered.** `test_binding_cli.py:95-134` corrupts the real pending record and runs `credential-recover` in a subprocess: status 6, `type=CredentialBindingIncomplete`, `source_type=TypeError`, `phase=unknown`, coordinates present, no `key_ref`/`commit`, files unchanged. This is the exact operator-facing failure B1 described.
- **Negative control is honest.** `typeerror-negative-control.py.txt` reverts the tuple only in an in-memory re-exec of `sdk.emit` and re-binds `sdk.MappedCredentialProvider`; the lifecycle test imports from `sdk`, so the patched class is exercised. Three TypeError cases failing and the OSError case passing is the expected discrimination. The packet labels it as a control, not historical output.
- **Docs updated as requested.** `consistency-c9-setup…md:47` and `libs/sdk/README.md:228-229` now say OSError/ValueError/TypeError.
- **Optional gap closed.** `test_credential_lifecycle.py:272-292` asserts `CredentialBindingRecoveryRequired` for the absent legacy candidate (`binding.py:980-984`).
- **Evidence consistent.** SDK 599 / CLI 30 / Ruff clean; wheel status shows all four changed files hash-matched. Custody is unchanged so its absence from `source_checks` is fine. Architecture/custody suites were not rerun, which the doc states plainly; the tuple change cannot affect them.

## Optional observations (non-blocking)

- **Remaining narrowness is deliberate.** Custody `assert` statements (`binding.py:927`, `:943`) and any `KeyError` from a schema-valid-but-incomplete intent would still escape as status 70. Consistent with the packet's refusal to broaden the catch; worth a sentence in the custody README if it ever bites.
- **Intent-record byte invariance** (`test_credential_lifecycle.py:226`, `record_kind="intent"`) depends on `_intent_for` reading the token index before publishing the pending marker. The excerpts do not show that ordering; the passing test is the evidence.
- **Legacy-import recovery refusal still publishes the token index** (`binding.py:968`) before raising at `:982`. Not claimed otherwise, just not asserted.

ACCEPT.

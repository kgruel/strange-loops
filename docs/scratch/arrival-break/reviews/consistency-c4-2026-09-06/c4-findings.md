# c4 — Fable review

Effort: low. Finished: 2026-09-06T19:01:27.276413+00:00.
Packet SHA-256: `3e2feabf76d9c8a9a01a143512d337b045c00e3af17199ab7c43fba6ff36a73e`.

Static reviewer output; findings still require primary triage.

**Verdict: accept.** The diff does exactly the accepted C4 scope. No blockers; three optional notes.

**Scope check against the diff**
- Refusal is immediate: `emit.py:96-99` raises before any attribute assignment or resolver call. `for_write` (`emit.py:101-107`) is byte-identical to baseline, so no key selection or signing-domain change.
- Error taxonomy: `SdkValueError` (`types.py:71`) is both `SdkError` and `ValueError` and is already exported (`__init__.py:78`, `175`). No new type or envelope.
- Positional and keyword forms share the same rule since the parameter stays positional-or-keyword. Both are tested (`test_emit.py:228-269`). `Path("")` and `""` are non-`None` and correctly refused.
- Default and explicit-`None` paths are unchanged and now verified end to end under all three domains against the minted public key (`test_emit.py:205-225`).
- Rejection test is self-checking: monkeypatching `sdk.emit.tick_signer_for` etc. would raise `AttributeError` if those were not module attributes, and the sentinel/absence assertions cover filesystem side effects.
- README text is accurate. The `grant_observer` registration gap (`kind.py:468-477`) and initializer custom-credential requirement (`declare.py:505-527`) are pre-existing API limitations, correctly kept out of C4.

**Findings (all optional, none regressions)**

1. **Low, test brittleness.** `test_emit.py:209-210` hardcodes observer `"test"` for the fact and Arrival signers. This only verifies against the flat self key if the `sample_vertex` fixture stem is `test`. Trigger: someone renames the fixture file. Consequence: a spurious failure that looks like a signing regression. Correction: use `sample_vertex.stem` instead of the literal.

2. **Low, coverage narrowing.** The baseline test also minted a nested `admin` key (`ensure_signing_key(sample_vertex, "admin")`); the rewrite drops it. Trigger: a later change to `_scoped_signer_for` observer resolution (`signing.py:277-298`). Consequence: the provider test no longer exercises the per-observer key path, only the self key. Correction: keep the `admin` mint and assert `fact_signer("admin", ...)` verifies against that keypair's public key.

3. **Low, documentation.** The class docstring (`emit.py:93`) still reads only "Bridge custody's disk keypair management..." and does not mention the `key_dir` refusal; the README note is spliced into the middle of the `emit_batch` bullet list (`README.md:172-179`) rather than under a provider heading. Trigger: a reader using `help()` or scanning the API list. Consequence: discoverability only; content is correct. Correction: add one sentence to the docstring and move the README paragraph after the list.

No existing limitation was misrepresented as fixed, and no signing, verification, or registration behavior changed.

# custody-observer-guard — Fable review

Effort: low. Finished: 2026-09-06T14:31:37.914054+00:00.
Packet SHA-256: `02fc77ddef79f327db58b640aeafb4234148df1e584137879b430d0dca2f453c`.

Static reviewer output; findings still require primary triage.

**No actionable defects found** in the excerpts. Checked below; two conditional concerns follow.

**What was checked**

- `_valid_key_observer` (`signing.py:37-44`): rejects empty, `.`, `..`, empty components (so `/abs`, `a//b`, `a/`), and NUL. Absolute POSIX paths fail via the leading empty component. Nested names like `kyle/loops-claude` still pass, and `kyle` vs `kyle/loops-claude` resolve to distinct key files, so no aliasing between valid IDs. No regression for dotted, spaced, or hyphenated names.
- Guard ordering in `ensure_signing_key` (`signing.py:70-75`): validation precedes `load_or_generate` and `.gitignore` writes, matching the tests that assert nothing is created on rejection.
- Self-observer fallback (`signing.py:139-146`): per-observer dir is preferred, flat key used only when `observer == vertex_path.stem`. Empty observer cannot collapse to the flat key because it is rejected before the path join.
- Domains: signer and verifier both thread the same explicit `domain`; tick verifier stays any-key by design, fact and arrival verifiers are exact-observer. Malformed declared keys are skipped and yield `False` for that observer, which surfaces as a break rather than a false pass.
- `declared_observer_keys` returns `{}` on non-`.vertex` or unparseable input, so verifiers degrade to "unchecked" rather than crashing.

**Conditional concerns (not demonstrated on supported paths)**

1. **Stem-vs-nested divergence for the self-observer** (`signing.py:73-75` vs `139-142`). If `keys/<stem>/ed25519.key` already exists, `ensure_signing_key(v, observer=stem)` mints or loads the flat key and returns its public key, while the signers prefer the nested key. A CLI that publishes the returned public key into the declaration would then verify against the wrong key. This requires a pre-existing nested self-observer dir, which no supported path in this excerpt creates. Worth a one-line check: if the nested dir exists for the stem, use it.
2. **Platform aliasing.** On case-insensitive filesystems (macOS default) `Alice` and `alice` share a key directory; on Windows `..\x` is a single "component" and would traverse. The registry lookup is exact-string, so neither produces a false verification pass, but the signer could sign with another observer's key. Only relevant if those platforms or case-variant observer names are in scope.

Remaining uncertainty: how callers derive the self-observer identity (stem here vs declaration `name` elsewhere) and whether `ed25519.load_or_generate` has any path handling of its own; neither is in the excerpt.

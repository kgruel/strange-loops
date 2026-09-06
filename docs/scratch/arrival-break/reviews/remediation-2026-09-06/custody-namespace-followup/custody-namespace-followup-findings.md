# custody-namespace-followup — Fable review

Effort: low. Finished: 2026-09-06T15:11:48.324111+00:00.
Packet SHA-256: `6d21d63188cedfd6c298b02d523f50817a420950173bde0633a484dadf9f2811`.

Static reviewer output; findings still require primary triage.

Static review of the current custody patch. One actionable defect, plus questions. Everything else in the listed fix set checks out against the stated policy: reserved basenames are rejected before any mkdir, reserved self stems never probe a directory, exact-only self fallback allows `Alice` flat with `alice` nested in either order, exact-self symlinks and non-directory components refuse, and the missing-locator init path works.

**Defect 1: exact-name comparison breaks on Unicode-normalizing filesystems**
- Span: `libs/custody/src/custody/signing.py:75-84` and `:103` (recheck after mkdir).
- Trigger: a non-ASCII observer such as `"jos\u00e9"` (NFC) on a filesystem that stores and returns names normalized (HFS+ external or legacy volumes, some SMB/NFS mounts; APFS is normalization-preserving so the default macOS volume is not affected).
- Consequence: `mkdir` creates the directory under the normalized name, then the recheck in `_ensure_observer_key_dir` calls `iterdir`, finds no byte-exact match, sees `candidate.exists()` true, and raises "aliases existing custody". The observer's own first mint fails and leaves an empty directory. Every later `ensure_signing_key` and every fact or arrival signer call for that observer refuses permanently. There is no alias here, only one observer.
- Reproduction outline: create an HFS+ disk image, place a vertex there, call `ensure_signing_key(v, observer="jos\u00e9")`, observe ValueError and an empty `keys/josé/` directory. Portable simulation: monkeypatch `Path.iterdir` to yield names via `unicodedata.normalize("NFD", ...)` and `Path.exists` to be normalization-insensitive.
- Scope note: this is a consequence of the chosen exact-label policy meeting a normalizing filesystem, not a case issue. If normalizing filesystems are declared out of scope like Windows, document it; otherwise the check needs to treat the directory this process just created as exact.

**Questions, not defects**
- Dangling symlink at a case variant: on a case-insensitive filesystem with a dangling symlink `keys/alice`, `observer="Alice"` passes `_observer_key_dir` (line 80 `exists()` is false for a dangling link), then `mkdir(exist_ok=True)` at line 102 raises a raw `FileExistsError` instead of `ValueError`. No key is minted, so this is a message-type inconsistency only. Is a non-ValueError acceptable on that path?
- Pre-patch layout with a reserved self stem: a vertex `ed25519.key.vertex` that previously minted nested `keys/ed25519.key/` now makes `_load_existing_keypair(keys_root)` raise `IsADirectoryError` rather than `FileNotFoundError`, so all signer factories raise instead of returning None. Migration is out of scope; confirm the loud failure is the intended posture.
- Non-self observer named `ed25519` (no extension) is permitted and creates `keys/ed25519/` beside `ed25519.key`. No collision with the key files or the mkstemp `.ed25519.key.*` temporaries, so this looks fine, but confirm it is intended given the reservation wording.

No findings in the test file: the simulated exists/iterdir/mkdir cases and the APFS skip guards match the behaviors above.

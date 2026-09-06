# custody-and-followup — Fable review

Effort: low. Finished: 2026-09-06T15:00:58.462562+00:00.
Packet SHA-256: `688a491283d6e1cdc44bac1cd90b89c94f703211e7bf7346b1a0fb03dcea7622`.

Static reviewer output; findings still require primary triage.

Static review only; nothing was executed.

**Finding 1 — Medium. Observer names equal to the reserved key basenames corrupt the flat layout.**
Span: `signing.py:37-44`, `signing.py:184-187`, `ed25519.py:117-120`, `ed25519.py:152-153`.
`_valid_key_observer` accepts `ed25519.key` and `ed25519.pub`. For a non-self observer named `ed25519.key`, `_ensure_observer_key_dir` runs `mkdir` on `keys/ed25519.key`, creating a directory at the flat private-key path. Afterwards every self-key path breaks: `ed25519.load(keys_root)` raises `IsADirectoryError`, which `_load_existing_keypair` does not catch, so `tick_signer_for`, both scoped signers and `ensure_signing_key` raise a raw OSError instead of returning None or a custody ValueError. The same holds for `alice/ed25519.key`, which pre-creates a directory under an unminted `alice`, and `_generate` then suppresses `FileExistsError` from `os.link` against that directory and fails later in `load`. No wrong identity is published, but the vertex is left unable to mint or load its self key until the directory is removed by hand.
Repro: `ensure_signing_key(v, observer="ed25519.key")` on a fresh vertex, then `ensure_signing_key(v)` or `tick_signer_for(v)`. Expect ValueError at declaration time; observe `IsADirectoryError`.

**Finding 2 — Medium (design question). A case-variant nested observer refuses an unambiguous flat self key on case-insensitive filesystems.**
Span: `signing.py:139-142`, `signing.py:72-81`.
`_self_key_dir` always probes the nested self directory, even when the flat key already exists. With vertex `Alice.vertex` and flat key minted, `ensure_signing_key(v, observer="alice")` succeeds and creates `keys/alice/`. From then on, `_observer_key_dir(keys_root, "Alice")` finds no exact `Alice` entry, `candidate.exists()` is true on APFS or NTFS, and it raises. Consequence: `tick_signer_for`, `fact_signer_for`, `arrival_signer_for` and `ensure_signing_key(v)` all raise ValueError on macOS while working on Linux, so the CLI crashes rather than signing with the flat key it holds. The policy says aliases refuse before a nested key exists, but here the flat key is the retained, unambiguous self key, and the refusal is only about a fallback location. Either the nested probe should be skipped when the flat key is present, or minting a case variant of the self name should be refused up front. The reverse order also blocks initialization entirely: mint `alice` nested first, and `Alice` can never get a self key.
Repro on macOS: write `Alice.vertex`, `ensure_signing_key(v)`, `ensure_signing_key(v, observer="alice")`, then `tick_signer_for(v)`.

**Finding 3 — Low. Reserved-name and directory-shaped failures surface as OSError from load helpers.**
Span: `signing.py:99-106`, `signing.py:210-212`, `signing.py:258-261`.
`_load_existing_keypair` maps only `FileNotFoundError` to "unsigned era". `NotADirectoryError` (observer name that resolves to an existing regular file, for example observer `ed25519.pub` when the flat layout exists, since `_observer_key_dir` returns the file itself at line 88) and `IsADirectoryError` propagate through the signer callables mid-operation. Callers of the fact and arrival signers get an exception from the engine's signing hook for a single observer rather than an unsigned fact or a refusal at signer construction. Repro: `ensure_signing_key(v)`, then `fact_signer_for(v)("ed25519.pub", "digest")`.

**Finding 4 — Low (test gap). The case-alias branches have no deterministic coverage.**
Span: `test_signing.py:99-113`, `133-148`, `277-287`; `signing.py:72-83`, `92-96`, `114-122`.
Every test of the case-alias refusal skips on a case-sensitive filesystem, so Linux CI never executes `signing.py:77-81` or the post-`mkdir` recheck in `_ensure_observer_key_dir`. The symlink test covers line 84 only. A regression in the `candidate.exists()` branch would pass CI. Suggest a test that monkeypatches `Path.exists` or `iterdir` to simulate a differently spelled existing entry, plus one that patches `Path.mkdir` to create the other spelling to exercise the post-mkdir recheck that the race policy relies on.

**Finding 5 — Question, not a bug.** `_generate` (`ed25519.py:109-122`) relies on `os.link` succeeding on the keys root. Filesystems that refuse hard links (some SMB and FAT mounts) will raise a bare OSError from `load_or_generate` and never mint. Is that an accepted limitation for a caller-configured keys root, or should the error be mapped to a custody refusal with a clear message?

No defects found in `transfer.py` for this pass: the close-failure note path, non-replacement of existing output, and published/unpublished classification read correctly. `_owns_tick` and the hydration regression also read correctly.

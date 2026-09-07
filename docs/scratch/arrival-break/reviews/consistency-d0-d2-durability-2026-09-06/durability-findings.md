# durability — Fable review

Effort: low. Finished: 2026-09-07T00:01:21.643770+00:00.
Packet SHA-256: `376ad9ba3720935261fe603908001efab0fbae99810687445b1a2c97558ced12`.

Static reviewer output; findings still require primary triage.

**REVISE.** One correctness blocker inside the stated scope; the directory-ordering and completed-slot/pending-index fixes otherwise hold.

**Blocker: `recover_binding` non-created provenance skips the key-directory fsync when both key files are already visible.** In `libs/custody/src/custody/binding.py:977-1001`, the legacy-import branch loads the pair, checks expected public key, and calls `_fsync_directory(key_dir)` only when `ed25519.pub` is missing. If the original import was interrupted inside `_copy_key` between `os.link` of `ed25519.pub` and the following directory fsync (`binding.py:216-219`, the same window root probed for `bindings-v1`), retry sees both files present, never fsyncs the key directory, publishes the binding, and reports success. That is exactly the "success relying solely on prior file visibility" pattern the finding forbids. `_ensure_created_key` (`binding.py:785`) and the completed path in `_intent_for` (`binding.py:655`) already fsync unconditionally; the legacy/existing-ref recovery branch is the one remaining asymmetry. Fix: call `_fsync_directory(key_dir)` unconditionally after the `require_public_file=True` reload at line 1000, keeping the contradiction checks (expected-public mismatch, missing-public refusal for existing-ref) ahead of it as they are now. Add a regression mirroring `test_completed_retry_resyncs_validated_binding_after_link_sync_interruption` for `import_legacy` interrupted at the key-dir fsync, asserting the key dir appears in retry fsync calls.

**Verified correct**

- **Creation ordering.** `_directory(create=True)` recurses only through missing ancestors, mkdirs, then fsyncs the full lexical parent chain, so a child entry is never relied on before its parent directory is synced. Retry after mkdir-succeeded/parent-fsync-interrupted re-enters the `create` branch's `_fsync_parent_chain` because the fsync is outside the `mode is None` guard.
- **Nested root/ancestors.** Interruption during ancestor chain fsync leaves the ancestor present and root absent; retry re-syncs the whole chain. Covered by the nested-ancestor test.
- **Read-only stays read-only.** `resolve` and `verify` use `create=False` everywhere and call no fsync or mkdir. `_root_dir(create=False)` returns False without touching the filesystem.
- **Symlink refusal.** Provider-owned targets are lstat-validated after mkdir/FileExists, so a symlink at root, subdir, or key-ref refuses. Trusted existing ancestors are only opened for fsync, matching the documented alias policy.
- **Linked-binding-before-fsync retry.** Completed path in `_intent_for` fsyncs `bindings-v1`, the key dir, `pending-v1`, and `intents-v1` after the retained-intent, key-ref, public-key, and token-index contradiction checks, not before. `_publish_binding`'s FileExists branch validates public-key equality before its fsync. `recover_binding`'s published branch mirrors this. Prior completed-slot and pending-before-index refusals are unchanged and still tested.

**Notes, not blockers**

- `_subdir(create=True)` and `_root_dir(create=True)` skip `_directory` when the directory already exists, so they alone do not re-sync a directory whose mkdir succeeded but chain fsync was interrupted. Correctness currently depends on every subsequent `_publish_no_clobber` and `_directory(key_dir)` re-syncing the chain. Consider routing existing directories through `_directory(create=True)` too so the invariant does not rest on downstream call structure.
- `_fsync_parent_chain` walks to `/` on every directory creation. It is harmless but repeated per publication; caching is optional.
- No test covers mkdir of the provider root itself succeeding with its parent fsync interrupted; the nested-ancestor test leaves root absent. The chain fsync makes it correct, but a direct regression would pin it.
- Tests intercept `_fsync_directory` calls and ordering. This verifies sync logic, not power-loss survival, as the durability doc states.

# export — Fable review

Effort: low. Finished: 2026-09-06T14:33:21.752890+00:00.
Packet SHA-256: `3ce16a32cdc43c60afff8094db2be2d8bf8e06dc534461bdbb5e481aa3df7d10`.

Static reviewer output; findings still require primary triage.

**Result: 2 actionable findings, 3 conditional concerns. No data-loss or false-success path demonstrated on the supported file-backend route.**

## Actionable findings

**1. Medium — source-side OSError is misreported as a publication failure.**
`libs/sdk/src/sdk/transfer.py:93-115`. The `except OSError` wraps the entire drain loop at `transfer.py:98`, not just the filesystem publication steps. The file backend's export drains `self._log.walk()` lazily (`arrival_file_backend.py:496-498`), which reads the ledger file during the loop.
- Trigger: the ledger file becomes unreadable mid-drain (deleted, rotated, EACCES, EIO). `walk` raises `FileNotFoundError`/`PermissionError`, both `OSError`.
- Consequence: the caller gets `ExportPublicationError` with outcome `artifact-not-published` and `result.byte_count == 0`, attributing a source refusal to output publication. The evidence category is wrong, and `normalize_exception` never sees the source error, so the SDK's `ArrivalRefusal` path is bypassed for a class of source failures. Nothing is published, so no false success, but the failure evidence is mismatched.
- Repro outline: monkeypatch `FileLedger.export` to return a records generator that yields once then raises `PermissionError("source")`; call `export_target`; observe `ExportPublicationError` rather than a source refusal.
- Fix shape: narrow the `except OSError` to the mkstemp/link/fsync calls, or drain inside its own try that re-raises non-publication errors unchanged.

**2. Low — published artifact inherits mkstemp's 0600 mode.**
`transfer.py:94,107`. `tempfile.mkstemp` creates the file with mode 0600 regardless of umask, and `os.link` publishes that same inode. Every export artifact is owner-read-only.
- Trigger: any successful `export_target`.
- Consequence: a transport artifact intended to be handed to another user, service account, or container cannot be read by them without a manual chmod. This is a real behavioral deviation from ordinary file creation and is silent.
- Repro outline: run `export_target` with umask 022; `stat(output).st_mode & 0o777 == 0o600`.
- Fix shape: `os.fchmod(fd, 0o666 & ~umask)` before fsync, or use `O_CREAT|O_EXCL` directly on the destination and drop the link step.

## Conditional concerns (not demonstrated from the excerpts)

**A. Drain-time chain verification depends on `walk`, which is not shown.**
`_verify_prefix` runs `Full` once (`arrival_transfer.py:54`), then `export` re-walks the log lazily and without a lock. `scan` only checks lineage and `rh` at the `through` ordinal (`arrival_file_backend.py:696-706`). The exported bytes are exactly the captured prefix only if `walk` verifies the hash chain on every pull. The docstrings claim it does. If it only parses grammar, a rewrite of an earlier record between verify and drain would export with the head check still passing. Question for the owner, not a bug from the evidence.

**B. `scan` can yield one record past the bound before refusing.**
`arrival_file_backend.py:708-717`. If a density gap skips the `through` ordinal, the record after it is yielded (line 709) before the loop breaks and `HeadMismatch` is raised. The export fails overall, so nothing publishes. Only reachable if `walk` does not enforce density, which the docstrings say it does.

**C. `CapturedExport.close` closes the registry-provided ledger.**
`arrival_transfer.py:88`. If `BackendRegistry.open` ever returns a shared or cached ledger instance, closing it on export exhaustion breaks other holders. From the excerpt, `open` appears to construct per-call, so ownership looks correct. Confirm no caching.

**D. Hard-link publication requires link support on the destination filesystem.**
`transfer.py:107`. On filesystems without hard links (some SMB/exFAT mounts) every export fails with `ExportPublicationError`. Acceptable if documented; not a correctness defect on the primary platform.

## What was checked and found sound

- Captured prefix bounding: lineage/ordinal bound, `head_at` hash membership, and `Full` verification all run before `export`; `prefix.head != selected` guard closes the records iterator before raising.
- Concurrent appends: `scan` stops at the captured ordinal and does not read past it.
- Resource lifetime: `open_export` closes query and ledger on every pre-return failure; `CapturedExport` closes on exhaustion, on explicit close, and on context exit, idempotently.
- Publication ordering: data fsync precedes `os.link`, `os.link` fails on an existing destination (including dangling symlinks and directories), directory fsync follows publication, and `published=True` is only set after the link succeeds. Temp is unlinked in all paths.
- Late source refusal: exception inside the `with os.fdopen` block closes the stream, the temp is unlinked, and nothing is linked. The test at `test_arrival_export.py:55-77` exercises this.
- `ExportResult` is rebuilt with the true `byte_count` only after a complete drain, so a partial write never reaches a success result.

## Remaining uncertainty

`ArrivalLog.walk`, `ArrivalLog.read`, `normalize_exception`, and `BackendRegistry.open` are outside the excerpts. Findings A through C hinge on their behavior. Whether `ArrivalError` subclasses `OSError` is unverified; the passing late-refusal test suggests it does not, which is why finding 1 concerns raw filesystem errors rather than backend refusals.

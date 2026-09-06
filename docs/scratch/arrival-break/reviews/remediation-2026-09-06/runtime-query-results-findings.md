# runtime-query-results — Fable review

Effort: low. Finished: 2026-09-06T14:52:48.475855+00:00.
Packet SHA-256: `4a8ba3d23617eb49230c5503e8b28264bc989fbd2959c85294aa951707effae7`.

Static reviewer output; findings still require primary triage.

**Verdict: one demonstrated defect, one open question. The four described fixes otherwise hold up on the shown code.**

**1. Medium: source-side error can be reclassified as ExportPublicationError.** `libs/sdk/src/sdk/transfer.py:114-124`. The temp stream is a buffered `os.fdopen(fd, "wb")`. When `exported.records` raises a source error mid-drain (ArrivalError or a source OSError, exactly the path the docstring guarantees), the `finally` runs `stream.close()` under `publication_errors()`. `close()` flushes the buffered tail, so an ENOSPC/EIO on that flush raises `ExportPublicationError(published=False)` *during* handling of the source exception. Python replaces the in-flight exception, so the caller sees an output-publication error with the source failure only as `__context__`, violating "source and output errors aren't interchangeable" and "source OSError must retain source classification". Reproduction outline: monkeypatch `FileLedger.export` to yield one chunk then raise ArrivalError (as in `test_late_source_failure_never_publishes_partial_output`), and monkeypatch the stream's `close`/underlying `os.write` to raise OSError on the flush; assert the raised type is ArrivalRefusal, observe ExportPublicationError instead. Fix shape: on a non-publication exception path, close the stream with output errors suppressed or attached rather than raised; keep the current behavior only on the success path.

**2. Question (missing context): `_owns_tick` for a vertex whose name is `None` or `""`.** `libs/engine/src/engine/vertex.py:777` compares `getattr(tick, "origin", None) == self._name`. If `Vertex._name` can ever be `None`/`""` on the supported Arrival path, originless ticks (`None`/`""`) compare equal and are treated as local, contradicting the docstring's "originless evidence is not local proof". If the loader guarantees a non-empty vertex name for every Arrival-backed vertex this is moot; nothing in the shown span establishes that. The parametrized test at `test_runtime_boundary_consumption.py:551` only covers a named vertex `"v"`.

**Checked and not defects:**
- Blob-prefix predicate (`arrival_file_backend.py:1194-1198`): `CAST(text AS BLOB)` preserves embedded NUL bytes and `length`/`substr` on BLOB are byte-based, so literal matching for `%`, `_`, `[`, `~`, NUL, and multi-byte UTF-8 is correct. Exact-match query reuses the same bound/filter/cursor clauses, so an exact row outside the page bound correctly falls back to prefix.
- Cursor pagination after the ambiguous-prefix first page re-runs the exact probe with the cursor clause; harmless since no row equals the prefix.
- `published` closure read (`transfer.py:94-103,132`) captures the cell, so the directory-fsync failure correctly reports `published=True`.
- Recovery `file_written` (`arrival_declarations.py:1304-1354`) is set only in the two `_publish_cache` branches; already-published cache yields `False`, `phase="published"`, `commit=None`, `changes=None`.
- `plan_pending_boundaries` edge selection compares on microsecond-rounded tick time with receipt coordinates as tiebreak, matching the stated same-event-time consumption rule.

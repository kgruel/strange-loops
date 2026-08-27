QUESTION SET — combined-read fold fork, plus KEEP-fence locations.

1. Find vertex_reader.py (full path). Quote verbatim, with exact line ranges, the code at/around lines 390 and 403-406 — the combined-read fold fork. Extend to the enclosing function(s) boundaries and report those ranges.
2. Find the sdk read path: a read.py under libs/sdk — quote the function(s) that perform combined reads across stores, exact line ranges, verbatim key lines (the fork/branch points only, not whole bodies over 40 lines).
3. Enumerate callers of the combined-read path (who calls these vertex_reader/sdk read functions) — file:line, verbatim call line.
4. KEEP-fence locations (locate only, these must NOT change): (a) Spec.replay_from definition — file:line, verbatim; (b) VertexHandle checkpoint machinery — the class/methods, file, line ranges, method names; (c) benchmark arms — the benchmark files/functions under benchmarks/ touching fold or ingest, paths + top-level function names with lines.

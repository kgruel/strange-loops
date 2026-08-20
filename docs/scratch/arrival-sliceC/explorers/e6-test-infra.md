QUESTION SET — test infrastructure for the gate, plus Rule 17.

1. Conformance lens vectors: locate the conformance vector infrastructure (search tests/ and libs/ for conformance, vectors) — directory layout, the loader/harness file:line, one example vector file path, and the code that runs vectors through lenses (file:line, verbatim key lines).
2. Checkpoint dispatch tests: locate tests exercising VertexHandle checkpoint dispatch / replay_from — file paths, test function names, line numbers.
3. Rule 17: in the architecture test suite (search tests for 'Rule 17' or rule_17 or a retired-vocabulary/prose scan test), quote the test verbatim with exact line range, and quote the specific code that decides WHICH FILES it scans (the glob/walk/git command). Report whether that file-selection code uses git ls-files or a filesystem walk, as a description of the code, and whether docs/scratch appears in or is absent from any exclusion list — quote the relevant lines.
4. Architecture test suite layout: list the architecture test files (tests/architecture/ or similar) with a one-line description each from their docstrings, file:line.
5. The rowid-survival ratchet from cut B: locate it — file, test name, line range, verbatim assertion lines.

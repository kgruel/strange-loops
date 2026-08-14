# Sol — libs-handoff-wave r6, minimal diff review

Prior attempts were interrupted by a tooling-side filter during generated-input
testing; this pass asks for STATIC REVIEW + existing-test execution only. Do
not author new test documents.

Scope: commit ee652ba6 (lang/vertex_mutation.py + tests), answering SOL-R5-01.

1. Read the diff of ee652ba6. Assess the scan's correctness by code reading:
   does the left-to-right escape-aware scan, combined with the pre-existing
   substring refusals, classify every string opener correctly or refuse before
   any construct that could be misclassified? Note any logic path where a
   mutation verb could still complete on input the scan misreads.
2. Run the committed suites: uv run --package lang pytest libs/lang/tests
   (includes TestScannerProvableDomain + R5 additions and the corpus
   round-trip oracle). Report counts.
3. Verdict: SOL-R6-NN findings if any; CONVERGED / NOT CONVERGED for the wave.

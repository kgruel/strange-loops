# Sol — libs-handoff-wave r7, final convergence audit (static + committed tests only)

Do not author test inputs during this run — the red-first repros are all
committed; execute and audit them.

Scope: two commits since your r6 static review — ead3906d (whitelist state
machine, answers SOL-R6-01/02) and cb385220 (intent-create O_CREAT|O_EXCL,
closes a previously-deferred S2-gate finding).

1. AUDIT THE STATE MACHINE (lang/vertex_mutation.py, _assert_scanner_provable_domain)
   against the KDL spec's construct list (strings: plain/raw/multiline;
   comments: //, /*, /-; newline set; escape forms; identifiers). The machine
   is refusal-only with states {code, plain_string, line_comment}. The
   convergence question is finite now: is every KDL construct either
   (a) handled by a state transition or (b) refused before it can be
   misclassified? Enumerate the construct list and give a per-construct
   verdict. Note any construct neither handled nor refused.
2. Run: UV_CACHE_DIR=/private/tmp/loops-uv-cache uv run --package lang pytest
   libs/lang/tests — includes TestScannerProvableDomainR6 +
   TestScannerWhitelistAddendum (18 red-first pins) and the corpus round-trip.
   Report counts.
3. Read the cb385220 diff (engine/ceremony.py): O_EXCL create as the pending-
   intent gate. Verify by reading: FileExistsError → typed refusal; failed
   post-create write unlinks; recovery still classifies partial intents as
   IntentCorrupt. Run: UV_CACHE_DIR=/private/tmp/loops-uv-cache uv run pytest
   libs/engine/tests — report counts.
4. Verdict: SOL-R7-NN findings if any; CONVERGED / NOT CONVERGED for the wave.

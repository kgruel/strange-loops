# SDK source execution — Fable 5.1 adversarial review

Date: 2026-09-05  
Status: queued; invocation prohibited before the reported 21:20 CDT quota reset

The complete static packet is `/tmp/loops-arrival-review/sdk-source-prompt.txt`. It contains the accepted source design, full SDK source implementation/types/tests, supporting engine source/runtime/error/target code, validation evidence, and the review constraints. Its SHA-256 is `d18750eac7388576cb2659731b6239da5eddf930861d09994eb6b9e3b30754f4`.

The queued Python runner is `/tmp/loops-arrival-review/sdk-source-review-run.py`. It will pass the packet through `subprocess.run(input=...)` to `claude-fable-5-1[1m]` with safe mode, no tools or session persistence, at most eight findings, and no more than 1,500 words. The result will be stored at `/tmp/loops-arrival-review/sdk-source-result.json`.

No invocation was made before quota reset. Verdict, exact model metadata, dispositions, and post-review rechecks remain pending.

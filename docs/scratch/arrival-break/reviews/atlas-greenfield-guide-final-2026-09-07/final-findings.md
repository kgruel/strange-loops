# final — Fable review

Effort: low. Finished: 2026-09-07T06:04:00.924270+00:00.
Packet SHA-256: `75e0530016a3372eea4b65c6442dc933e2677abca5f3830f488c045debc72caa`.

Static reviewer output; findings still require primary triage.

**Verdict: REVISE.** Two blockers, both prose; the executed script and evidence are consistent and I found no semantic errors in the fold/verify/export/exit-6 claims.

**Blockers**

1. **Run instructions vs. `set -euo pipefail`** (`docs/guides/atlas-greenfield-cli.md:15-18`, `:27`, `:257`).
   Trigger: a beginner follows "run the Bash blocks in one Bash session" by pasting into an interactive shell. Consequence: `set -e` terminates the terminal on the first failure and `set -u` breaks common prompt hooks, so the `Workspace:` path and the retained-evidence instructions in "If a command is interrupted" are lost. The replay did not test this path; it ran the six blocks as one script file. Minimal correction: say to save the six blocks into one file and run it with `bash file.sh`, which matches how it was tested, and note that pasting interactively with these options is not supported.

2. **Declaration result shape is misdescribed** (`docs/guides/atlas-greenfield-cli.md:244-246`).
   Trigger: reader looks for `phase` and a top-level head in `declaration.json`. Consequence: the fields do not exist as stated. The root checker asserts `status == 'applied'` and reads heads only from `commit.before` and `commit.after`; it asserts `phase` on init only. Minimal correction: "declaration editing reports its `status` and a commit with before/after heads."

**Optional improvements**

- `:243` says emit-batch gives "each item's signing status"; items also carry `witnessed` and `stored` per the checker, so say "per-item signed/witnessed/stored evidence".
- `:40` mention that `uv sync` may rewrite the checkout's ignored uv.lock; the replay record says this but the guide does not.
- `:273` the "successful initialization removes its intent" claim is untested here; either hedge as "per the CLI reference" or leave as is, since it only affects an unexecuted text block.
- `:15` Python floor "3.11+" is unverified; evidence shows 3.13 only. Harmless if the SDK metadata declares 3.11.

Everything else checked out: observer/namespace/vertex name distinctions, binding before init, proposal split scoped to the fresh scaffold, whole-snapshot source-index caveat, receipt-order fold with the shared-key caveat, configured-vs-live wording, verify scope, sync as explicit check, export as captured prefix only, and recovery blocks marked as reference text.

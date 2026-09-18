# Fresh copy rehearsal commands

Worktree: `/Users/kaygee/Code/loops-wt/arrival-finish`, branch `arrival/finish`.
Private sandbox: `/Users/kaygee/Code/loops-rehearsals/loops-20260918-171627`.
The copied descriptor names the already audited prepared source. Private keys
were copied from the existing isolated rehearsal work directory; none is included
in these artifacts. Inputs and live preservation hashes are in the JSON evidence.

Successful run (after the receipt-observer fix and first review corrections):

```sh
uv run python scripts/arrival_rehearsal.py \
  --sandbox /Users/kaygee/Code/loops-rehearsals/loops-20260918-171627 \
  --vertex /Users/kaygee/Code/loops-rehearsals/loops-20260918-171627/fresh-work-2/.loops/project.vertex \
  --source /Users/kaygee/Code/loops-rehearsals/loops-20260918-171627/prepared/project.jsonl \
  --legacy-key-dir /Users/kaygee/Code/loops-rehearsals/loops-20260918-171627/fresh-work-2/.loops/keys \
  --output /Users/kaygee/Code/loops-rehearsals/loops-20260918-171627/fresh-rehearsal-run-2 \
  --observer project --runtime-epoch fresh --emit-kind seal \
  --emit-payload-json '{"message":"Fresh-epoch isolated copy rehearsal only; not live project history","rehearsal_only":true}'

uv run python scripts/arrival_rehearsal_recovery.py \
  --sandbox /Users/kaygee/Code/loops-rehearsals/loops-20260918-171627 \
  --evidence /Users/kaygee/Code/loops-rehearsals/loops-20260918-171627/fresh-rehearsal-run-2/evidence.json \
  --output /Users/kaygee/Code/loops-rehearsals/loops-20260918-171627/fresh-recovery-run-1 \
  --observer project
```

The main runner is intentionally one-shot; do not reuse these adopted descriptor
or output paths for another run. The later `--expect-tick` option additionally
attests the physical tick's signature and predecessor during a new rehearsal.
For this completed run, a read-only supplementary invocation of
`attest_tick_commit` uses the original recorded commit range 4485..4486 and the
reviewed project public key. The original returned Commit records were not saved,
so that supplement explicitly leaves `physical_matches_commit` null.

The full tick audit is separate from Arrival Full verification. Reproduce the
raw/prepared/Arrival historical window comparison with `uv run python
window_diagnostic.py` using the archived script in this directory; it reads only
private sandbox stores and writes metadata there. The standard deep audit caps
reported locations at ten. The complete independent comparison counted all 39
historical mismatches and zero post-anchor failures.

All SDK postchecks used the main runner's isolated `runtime/{state,config,data,
cache,loops}` directories. No live SDK open/write was used for verification.

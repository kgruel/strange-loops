# Installed handoff inventory and disposable host rehearsal

Source: `d8063488430efcd26153efdf6a9b8f6b86b699f8` (`arrival/finish`).
This is readiness evidence, **not installation, writer quiescence or cutover**.
The inventory and rehearsal commands did not change existing installed settings,
executables or main, or open live stores/private Loops credentials. This says
nothing about other running actors. Installed-route inspection was static;
host runs and generated stores/credentials used disposable roots. Unsandboxed
build/test commands ran from the source worktree with isolated state roots,
downloaded dependencies and may have left gitignored build/cache artifacts.

## Installed boundary observed

| Route | Observation | Handoff obligation |
| --- | --- | --- |
| PATH `sl`, `loops` | Both import `loops.main:main`; `loops-min` is absent. The `strange-loops` uv receipt and distribution metadata identify an **editable** installation from `~/Code/loops`, version `0.11.0`. | Advancing main changes the installed source immediately, even without resync; stale entrypoints may break rather than switch clients. Freeze it until consumers are accounted for. Use a clean root-wheel environment, not an upgrade inferred from the unchanged version. |
| Main checkout | Still `main` at `d904ccbac4f6672789b7eb475123a0faa05a16a9`. | Branch push is not main advancement or installed handoff. |
| Claude plugin | User settings enable `loops@gruel`; cache and registered directory source remain legacy `0.1.0`. The directory source is `~/Code/loops/clients/claude-code`. | Quiesce existing sessions and reconcile settings/cache/source before refresh, update or override. |
| Desired-state restoration | `~/.config/zsh/scripts/restore/restore-claude-plugins.zsh` installs plugins enabled in Claude settings. | Reconcile the desired state, not just a cached directory; do not execute restoration during the transition. |
| Shared live locator | `~/Code/loops-docs/.loops` is a **parent-directory symlink** to main's `.loops`; resolved paths and device/inode metadata confirm one descriptor, not two copies. Both project contexts reach the same JSONL. | Quiesce consumers in **both contexts**, then publish the canonical descriptor once. Do not migrate twice or delete the symlink target. Publication changes both views but does not retire their legacy callers. |
| Launcher | `~/.config/loops/bin/launch` uses legacy `read identity` and `emit session`, then starts Claude. | Retire or deliberately replace this route; do not silently translate its arguments. |
| Other project hooks | Two inspected hook implementations, registered by three other project settings files, call legacy reads/identity commands; one also invokes a remote CLI. | Global aliases/plugin replacement affects other projects. Their owners must approve retirement or a separate handoff; no remote inspection or execution occurred. |
| Aggregation and collectors | User `project` and `cli-completion` declarations reference the live project locator. Other inspected declarations contain source commands. | Inventory users and schedulers; a declaration is not proof of an active job. Legacy reads may maintain derived state, so “reader” alone is not a quiescence exemption. |

A native Claude process and a background-job record were present. Neither
process ownership nor loaded-hook state was established from executable/CWD
metadata. No processes were stopped. The inspected user crontab was absent;
19 user/system LaunchAgent/LaunchDaemon plists contained no direct Loops CLI
command. Two referenced unrelated script paths were missing. This is **not** a
transitive service audit or proof that no scheduler/writer exists.

The bounded scan covered selected user/project Claude settings, installed plugin
registrations and hook files, shell startup references, immediate project
locators, Loops worktree metadata, user Loops declarations, and process/CWD
metadata. It did not search transcripts, private keys, store contents, all
nested repositories, remote machines, or arbitrary running-process environments.
Full machine-local evidence stays outside the repository.

Replacement also removes the old `/loops:sweep`, `/loops:reconcile`, loops and
release skills, orientation lenses and turn-capture reminder. Account for those
manual/agent workflows; disabling hooks alone is not their replacement.

## Actual-host rehearsal

Fresh root wheel and fixed four-file plugin staged from the source above:

- Wheel SHA-256: `bd9bb107c08a4cc1846b41b2f4494d13f1c43e9c98f522e8f4af2dc5838ec197`.
- CPython **3.13.11**; native Claude Code **2.1.283**, non-interactive `-p` mode.
- Greenfield Arrival authority and newly generated, mapped synthetic credentials.
  This was **not** a migrated live-store rehearsal.
- All HOME/LOOPS_HOME/XDG/Claude/uv roots were disposable; no inherited hook selector,
  `HOOK_*`, `PYTHONPATH` or `PYTHONHOME`. Hook PATH selected the new wheel's Python.
- No tools or MCP servers; one deterministic loopback API response per case.
  Host token/model/cost fields describe that stub exchange, not a real model run
  or Fable review.
- The additional macOS sandbox allowed reads by default, with deny rules for
  `~/Code`, `~/.config/claude`, `~/.config/loops` and `~/Library/Keychains`.
  Other home locations were isolated by environment redirection, not a read
  allowlist. Policy also restricted writes to the rehearsal tree (plus device
  sinks), the security executable/securityd lookup, and outbound connections
  except the local stub. Canaries tested file read/write rules, **not** the
  network or keychain rules. Sandbox-related host warnings remain in the logs;
  this is not full host certification.

The repository's alias and registered-command smoke scripts passed against the
disposable venv, not the installed legacy PATH aliases. The plugin README changes
in this documentation checkpoint; the tested hook files and registration do not.
The host then exercised the **unchanged staged registration commands**:

| Scenario | Observed result |
| --- | --- |
| Explicit 5,000 ms SessionEnd budget | One open, close, seal and own-vertex tick. Startup context reached the API request. |
| No hook configuration selector | Host/hooks returned success; ledger bytes unchanged, no ordinary facts or ticks. |
| Default budget; test wrapper delays close launch 2.2 seconds | Open only, no close/seal/tick; debug log reports SessionEnd cancelled. Host still returned **0**. Plugin `timeout: 60` did not raise the shared budget. |
| Same delay; explicit 5,000 ms budget | Close, seal and tick completed. This demonstrates the budget control, not that five seconds suffices under every load. |
| Inline `--settings` hooks | With `--setting-sources ""`, both explicitly supplied no-write markers and the Arrival plugin ran. User/project settings-file hook merging was not exercised. |
| Cached legacy-name control | A no-write `loops@gruel` 0.1.0 fixture ran Start/Stop/End markers; Arrival ledger unchanged. |
| Same-name `--plugin-dir` override | The only `loops` plugin was `loops@inline` 0.2.0; its lifecycle completed and no cached-fixture markers ran. The control above prevents a vacuous “old hooks absent” pass. |

The cached fixture was **not the legacy runtime**. No installed cache was
modified. This establishes name precedence for the tested host/session shape,
not marketplace-update behavior or retirement of already-running sessions.

A separate **primary-authored** post-run validator checked exact fact order/payloads, one tick
referencing the seal and containing closed session state, signature presence,
Full ledger verification, empty Stop output, selected plugin identity, marker
counts, and stable ledger hashes after the delayed tests. Full verification
covers grammar/density/lineage/hash-chain, **not signature authorship, external
key trust or projection correctness**. No automatic retry was used.

Primary inspection found successful SessionEnd's structured close/seal diagnostics
absent from captured host stdout, stderr and debug log; the latter recorded only
completion. This absence was not a machine-checked validator assertion.
Post-exit ledger read-back supplied the terminal evidence in this rehearsal.
Do not treat a successful Claude result or an absent error as proof of closure.
Missing terminal evidence remains unknown; do not replay the write blindly.

Not exercised: interactive resume/clear/fork/compact dispatch, enabled Stop
nudging, user/project settings-file hook merging, marketplace refresh/update,
migrated production declarations, actual provider authentication, remote hosts,
or live writer exclusion. Nor did these host cases cover cancellation after
close launch/between close and seal, `enabled:false`, unsigned facts, nonzero
hook failure display, or undelayed End with the default budget (the runner's
`default-budget` option was not run).

Local evidence: `/tmp/arrival-handoff-inventory.LXeXS2/`, including
`artifact/evidence.json`, `host-validation.json`, seven `cases/*/` directories,
runner snapshots, invocation environments, sandbox canaries, host logs and
synthetic ledger read-back. The evidence is **ephemeral**, not yet durably archived;
preserve it before temporary-directory cleanup or rerun the rehearsal. Generated
stores and credentials are never production inputs. `evidence-manifest.json`
pins 108 allowlisted evidence files, excluding private credential material;
its SHA-256 is `ff3f3da443b045ddf5f2e04d8405919d9f87f140815e09d0c5c72d8b9da20250`.
This is a drift check, not independent proof of execution or a durable archive.

## Next gates

1. Approve the **scope of installed retirement**. Global aliases/plugin changes
   reach beyond this project; no such change is authorized by this report.
2. Resolve the shared-source locator and all relevant hook, launcher, manual,
   SDK and scheduler routes. Record owners, stopped/disabled state and prevention
   of new sessions; account for shutdown hooks before freezing the source.
3. Rehearse the selected installation/configuration and actual target declaration
   in isolation. Select the tested CPython **3.13.11** explicitly, not a loose
   `--python 3.13` selector. A separate unpinned 3.14.6
   run failed unchanged engine test
   `test_write_surface_reason_total_over_non_searchable_dir`; the cause is not
   established and 3.14 operational readiness is not claimed.
4. After explicit quiescence, take a **new** coherent snapshot and repeat the
   migration, report/provenance, fresh adoption, publication and recovery gates
   in the [cutover plan](loops-live-cutover-plan-2026-09-18.md). Neither this
   synthetic fixture nor the September 18 copy can become the live candidate.
5. Separately authorize installed handoff, main advancement and live publication.
   Record the exact root-wheel entrypoints, host version, selectors, credentials,
   state root and SessionEnd budget. Preserve originals and recover forward after
   the first authoritative Arrival write; never re-enable a legacy fallback.

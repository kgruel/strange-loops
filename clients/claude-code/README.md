# loops — Claude Code plugin

This development plugin (version `0.2.0`) provides one explicitly configured
Arrival adapter for `SessionStart`, `SessionEnd`, and `Stop`. It has no
commands, skills, target discovery, identity defaults, CLI PATH lookup, legacy
CLI fallback, retry, or exactly-once guarantee. The host resolves `python3`
through PATH; Python 3.11 or newer is required.

## Staging a plugin directory

From a checkout, stage the fixed plugin files into a **new** output directory
whose parent already exists:

```bash
PLUGIN_DIR=/absolute/path/to/new-loops-plugin
python3 clients/claude-code/build_plugin.py "$PLUGIN_DIR"
```

The builder copies only `.claude-plugin/plugin.json`, `hooks/hooks.json`,
`hooks/arrival_session.py`, and this README. It refuses any existing output,
including a dangling symlink, and never installs, enables, refreshes, or
removes a plugin. Treat a fresh output as immutable by convention: stage
another new directory for another build. **Any nonzero builder exit means the
output must not be activated**, even if all four files are present: copying or
post-copy verification may have failed. Inspect/remove failed output explicitly
or choose a different fresh path.

Staging alone is not installation or activation. The name/version guarantee
neither that legacy hooks stay active nor that they are replaced. A marketplace
refresh/plugin update from a source tracking this tree may replace cached
`loops@gruel` 0.1.0; a same-name `--plugin-dir` may take session precedence.
Marketplace refresh/update remains unrehearsed. A disposable non-interactive
rehearsal on Claude Code 2.1.283 observed same-name override against a no-write
legacy-name fixture; it did not exercise the legacy runtime or already-running
sessions. Replacement without an explicit configuration selector can silently
stop session capture because
the Arrival adapter defaults to disabled. Other or already-running sessions may
still have legacy writers.

Check the marketplace's registered path/ref before advancing it to this tree.
Do not refresh/update `loops@gruel` from a tracking source or launch a same-name
plugin override before legacy routes are retired/quiesced. Explicitly reconcile
cached plugins, user/project hooks and skills; a version bump proves no
merged-hook exclusivity. Host lifecycle rehearsal and live cutover remain
separate operator gates.

## Configuration

After retiring or quiescing other writer routes, use the staged `PLUGIN_DIR`
above. For source-checkout development only, it can instead be set to
`"$PWD/clients/claude-code"`. The adapter stays disabled without an explicit
configuration selector:

```bash
claude --plugin-dir "$PLUGIN_DIR"
```

Save the following JSON configuration at an absolute path, then select it explicitly:

```bash
export LOOPS_CLAUDE_HOOK_CONFIG=/absolute/path/to/claude-arrival.json
claude --plugin-dir "$PLUGIN_DIR"
```

```json
{
  "enabled": true,
  "binary": "/absolute/path/to/loops-min",
  "target": "/absolute/path/to/project.vertex",
  "credential_root": "/absolute/path/to/mapped-credentials",
  "credential_namespace": "tenant",
  "observer": "team/claude",
  "receipt_observer": "team/claude",
  "stop_nudge": false
}
```

`enabled` is a required boolean; `stop_nudge` is an optional boolean. When
enabled, the six other fields are required nonempty strings, and `binary`,
`target`, and `credential_root` are absolute paths. An unset or empty selector
disables the adapter before stdin, target, or child-process IO. `enabled: false`
reads only the selected configuration file.

Provision an initialized/adopted Arrival authority with a current projection
and mapped credentials separately; see `apps/loops-min/README.md` in the **same
source revision** used to stage this plugin. Retain that revision and any local
diff with your artifact; the operator guide is not bundled. The target must
admit the configured observer's `session` and `seal` facts. End requires a
vertex-level `boundary when="seal"`; declare a `session` fold keyed by `name`
if you want folded observer-keyed session state. Conditional boundaries can
legitimately produce `sealed: false`. The hook installs neither declarations
nor credentials. This README makes no production cutover claim.

Receipts expose `signed` separately from `stored` and `witnessed`. The hook
preserves the SDK's captured signing policy, including optional unsigned
facts; selecting a credential root does not itself require signing. Signed
workflows must provision the exact root/namespace/observer bindings.

Claude Code merges plugin hooks with user and project hooks. Retire old hook
wiring explicitly before enabling this plugin, or both can write session facts.
This plugin does not remove that wiring. Quiesce hooks before changing the
configuration, target descriptor, credentials, or executable: the separate
operations are not an atomic transaction.

## Behavior and evidence

`SessionStart` matches startup, resume, clear, and fork—not compaction. It
writes `session` open, validates its witnessed/stored Arrival receipt, then
reads Arrival-only summary plus at most five newest metadata facts. The inventory/activity orientation replaces the old fold/lens recipes.
Summary and activity retain their distinct read bases and stores; they do not
claim a common snapshot. Activity is not tick proof: seeing a seal fact does
not prove a tick.

`SessionEnd` writes close, **then validates its receipt**, then makes one seal
attempt. It never seals after an unconfirmed close and never retries an unknown
outcome. `sealed: false` is not success. End evidence is payload-free,
newline-delimited JSON on stderr: a confirmed-close/seal-pending record,
followed by a final outcome. A pending record proves neither seal attempt nor
completion. These diagnostics are for reconciliation, not agent context;
the host may discard output on termination. Nonzero hook failures may display
only the first stderr line (the pending record). Debug logs may aid reconciliation
but are not a durable receipt sink: primary inspection of the 2.1.283 rehearsal
found successful End diagnostics absent from captured stdout, stderr and debug
log. A missing terminal outcome remains unknown; a
successful Claude process exit does not prove close/seal completion.

Start context is ASCII JSON bounded below Claude Code's 10,000 UTF-16-unit
limit. If required evidence cannot fit, stdout is refused rather than clipped;
confirmed open evidence remains on stderr. Free-text diagnostics are bounded.
Reconciliation identities on stderr deliberately are not clipped, and fact
payloads are never forwarded.

`Stop` is disabled unless `stop_nudge` is true. With an inactive stop guard and
a nonempty last assistant message, it returns one neutral `additionalContext`
reminder, which continues the conversation. It never reads a transcript or
target.

The source-side evidence is in
`docs/scratch/arrival-break/installed-handoff-rehearsal-2026-09-27.md` in the
same checkout (not bundled in this plugin). It covers seven synthetic host
scenarios with a loopback model stub, including inline `--settings` hook
composition and a cancelled SessionEnd despite host exit 0. It does not establish
user/project settings-file hook merging, interactive resume/clear/fork behavior,
production authentication, migrated-store readiness or writer quiescence.

## SessionEnd timeout

Claude Code gives `SessionEnd` hooks a shared 1.5-second budget by default.
Set the exact environment variable in the launch environment when an operator
chooses a larger budget, for example:

```bash
CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS=5000 claude --plugin-dir "$PLUGIN_DIR"
```

The plugin sets its own SessionEnd timeout to 60 seconds so older hosts do not
retain their 1.5-second per-hook default. This does **not** raise the shared
budget: the operator still sets that budget, and the shorter limit applies.
See the [Claude Code hooks reference](https://code.claude.com/docs/en/hooks#sessionend).
A timeout or kill can leave a write outcome unknown; do not retry automatically.

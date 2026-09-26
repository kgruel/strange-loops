# loops — Claude Code plugin

This development plugin provides one explicitly configured Arrival adapter for
`SessionStart`, `SessionEnd`, and `Stop`. It has no commands, skills, target
discovery, identity defaults, CLI PATH lookup, legacy CLI fallback, retry, or
exactly-once guarantee. The host resolves `python3` through PATH; Python 3.11
or newer is required.

## Local development and configuration

Launch Claude Code with this checkout's plugin while developing it:

```bash
claude --plugin-dir "$PWD/clients/claude-code"
```

Save the following JSON configuration at an absolute path, then select it explicitly:

```bash
export LOOPS_CLAUDE_HOOK_CONFIG=/absolute/path/to/claude-arrival.json
claude --plugin-dir "$PWD/clients/claude-code"
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
and mapped credentials separately; see the
[loops-min operator guide](../../apps/loops-min/README.md). The target must
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
only the first stderr line (the pending record); inspect Claude Code's debug
log for the terminal outcome. A missing terminal outcome remains unknown.

Start context is ASCII JSON bounded below Claude Code's 10,000 UTF-16-unit
limit. If required evidence cannot fit, stdout is refused rather than clipped;
confirmed open evidence remains on stderr. Free-text diagnostics are bounded.
Reconciliation identities on stderr deliberately are not clipped, and fact
payloads are never forwarded.

`Stop` is disabled unless `stop_nudge` is true. With an inactive stop guard and
a nonempty last assistant message, it returns one neutral `additionalContext`
reminder, which continues the conversation. It never reads a transcript or
target.

## SessionEnd timeout

Claude Code gives `SessionEnd` hooks a shared 1.5-second budget by default.
Set the exact environment variable in the launch environment when an operator
chooses a larger budget, for example:

```bash
CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS=5000 claude --plugin-dir "$PWD/clients/claude-code"
```

The plugin sets its own SessionEnd timeout to 60 seconds so older hosts do not
retain their 1.5-second per-hook default. This does **not** raise the shared
budget: the operator still sets that budget, and the shorter limit applies.
See the [Claude Code hooks reference](https://code.claude.com/docs/en/hooks#sessionend).
A timeout or kill can leave a write outcome unknown; do not retry automatically.

# loops-min

`loops-min` is the agent-facing JSON process client for the headless `sdk`
package. It provides descriptor/read operations, verification, projection and
search maintenance, exact export, explicit restore-forward, and a mapped-only
Arrival writer surface. Empty-receiver import, admission, a generic replicate
command, and installed legacy writer cutover remain later work.

Writer commands require all of `--credential-root`, `--credential-namespace`,
and `--receipt-observer`. They never select locator-derived credentials or fall
back to a legacy writer or create keys implicitly. The founding binding must be
pre-provisioned for `init`; pre-provision every author and receipt binding used
by a signed workflow. Selecting the mapped provider does not make every domain
mandatory: an absent optional signer retains the SDK's unsigned behavior under
the captured declaration and signed-era rules. Callers should inspect each
result's `signed` and `witnessed` evidence.

Credential mutations are explicit SDK-backed commands. Their tokens name one
durable operation and should be retained with the JSON result or error:

```text
loops-min credential-create /keys --namespace tenant --observer alice \
  --token setup-alice
loops-min credential-recover /keys --namespace tenant --observer alice \
  --token setup-alice
loops-min credential-bind-existing-ref /keys --namespace tenant \
  --observer bob --token bind-bob --key-ref KEY_REF \
  --expected-public-key PUBLIC_KEY
loops-min credential-import-legacy /keys --namespace tenant --observer carol \
  --token import-carol --vertex old.vertex
```

`credential-recover` uses the exact namespace, observer, and token of a retained
binding intent. An incomplete result is a reconciliation boundary, not an
automatic retry instruction. Existing-reference binding and legacy import are
explicit selections; the client does not search for keys or serialize custody
implementation objects.

`init` always requests an Arrival file target and never uses `init_vertex`'s
legacy default. A minimal lifecycle is:

```text
loops-min init app.vertex --name app --location /data/app.arrival \
  --observer alice --credential-root /keys --credential-namespace tenant \
  --receipt-observer alice --strict
loops-min preview app.vertex item --payload-file payload.json --observer alice \
  --credential-root /keys --credential-namespace tenant --receipt-observer alice
loops-min emit app.vertex item --payload-json '{"value":1}' --observer alice \
  --credential-root /keys --credential-namespace tenant --receipt-observer alice
printf '%s' '{"value":2}' | loops-min emit app.vertex item --payload-file - --observer alice \
  --credential-root /keys --credential-namespace tenant --receipt-observer alice
loops-min emit-batch app.vertex --facts-file facts.json \
  --credential-root /keys --credential-namespace tenant --receipt-observer alice
```

`emit`, `preview`, and `seal TARGET` require exactly one of `--payload-json STRING` or
`--payload-file PATH`; `PATH` may be `-` for UTF-8 stdin (without a BOM).
`emit-batch` likewise
requires exactly one of `--facts-json STRING` or `--facts-file PATH`. Payloads
must be JSON objects; batch inputs must be arrays of JSON objects. Transport
JSON rejects duplicate keys, non-finite numbers, malformed UTF-8, and wrong
shapes before target or credential resolution. `preview` returns the public
SDK `preview_emission` result, including an `admitted: false` result when the
SDK declines admission; it does not append custody records or create credential
bindings. It may still update external witness state; its result is not a
complete filesystem-effects receipt. `emit-batch` passes observer, ID, timestamp, origin, and admission
fields to the SDK, retaining its existing defaults and coercion rules. `seal`
uses the same mandatory mapped credentials and delegates to `sdk.seal_fact`.
It is descriptor-only: a captured vertex `boundary when="seal"` is required;
the first such boundary supplies required match values. `sealed: false` means
this invocation produced no own-vertex tick; the underlying receipt distinguishes
a committed fact from an idempotent no-op. The client does not retry unknown
outcomes; stable IDs and the SDK's returned evidence are the reconciliation
boundary.

`summary TARGET --arrival-only` and bounded `facts TARGET --arrival-only`
require one explicit non-aggregate Arrival descriptor and never fall through to
legacy or aggregate readers. `facts TARGET --metadata-only` omits each item's
`payload` while retaining its envelope, page metadata, basis, and store; it can
be combined with `--arrival-only`. `facts` remains a bounded page with default
`--limit 50`. `facts TARGET --all` is mutually exclusive with `--limit` and
delegates once to `sdk.read_all_facts`; `--arrival-only` is accepted there as
redundant, while `--metadata-only` is refused as usage before the target opens.
`facts TARGET --all` returns a complete selected JSON materialization from one
current Arrival basis. It has no page-size flag, token, streaming, or
cross-process continuation.
An unsupported or truncated adapter result refuses rather than claiming a
complete history.

`declaration target.vertex --proposed-file next.vertex --observer alice ...`
passes the file's text to the SDK's captured declaration-edit protocol. If an
edit reports an intent after a durable interruption,
`declaration-recover INTENT` resumes it without resolving credentials again.
Likewise, `init-recover TARGET` uses only the target's reserved initialization
intent. It does not accept credentials, observer, backend, location, name, or
strictness overrides. It does not choose a new lineage or re-sign the reserved
bootstrap records.

`loops-min export target.vertex captured.jsonl` publishes a complete captured
wire prefix at a new pathname and returns the SDK manifest in its JSON result.
It never replaces an existing output. Export publication failures report
whether the complete artifact became visible before directory durability failed.

`loops-min restore-forward source.vertex receiver.vertex` restores an existing
exact copy through the witnessed source head. It preserves the receiver's
role and reports its before/after heads and commit receipt. Ordinary opens
continue to refuse older copies. Unknown or incomplete outcomes retain the
identity evidence needed to reconcile custody before repeating the operation.

Each successful invocation prints one `{"ok": true, "result": ...}` JSON
object. Failures print one JSON error object on stdout and a concise diagnostic
on stderr. Result objects are serialized with the SDK model's `as_dict()`;
continuation capabilities remain process-local and are reported without a
fake cursor token.

Exit status 2 covers argument, transport JSON, local input-file, and SDK
invalid-input/configuration errors (including missing founding credentials); 3
means a recognized unsupported operation or target; 4 is a target, custody,
projection, publication, or contract refusal/outcome; 5 is admission or
ceremony refusal; and 6 means ledger custody committed or may have committed,
or a credential-binding mutation is incomplete. Status
4 does not by itself prove zero derived or publication effects. Status 6 is
not permission to retry: the JSON error retains commit, IDs, intent, and
outcome evidence supplied by the SDK. A credential-binding incomplete result
has a binding token and phase rather than a ledger Commit or fact IDs; an
unknown phase does not prove that a durable binding intent exists.

For hooks, prefer the absolute `loops-min` binary from a **root-wheel**
installation: that is the installed artifact covered by the CLI/adapter smokes.
The workspace package is available for development, but its standalone wheel is
not covered by those installed-artifact tests.

A root-only installation maps `sl`, `loops`, and `loops-min` to this JSON client.
The legacy `apps/loops` distribution, its TUI/lenses, and detached boundary-job
dispatch are retired from this source tree. Existing installations can still
contain that distribution or an older root build. Mixing an old standalone
`loops` distribution with the new root wheel creates a last-writer-wins collision
for `bin/loops`; use a clean environment, not that mixed binding. The retired
`python -m loops` and `uv run --package loops` routes are not compatibility
entrypoints.

A Git update can leave ignored caches or private state under `apps/loops`.
Preview with `git clean -ndX apps/loops`; preserve/move aside any needed residue
under the operator handoff plan, never blind-delete it. Dev checks tolerate
ignored residue without treating the old directory as a workspace package.

Quiesce legacy hook/job consumers **before** replacing their live executables.
After checkout changes, `uv run`, `uv sync` or a path-source tool upgrade can
regenerate aliases without a separate manual install. Both root builds can
report `0.11.0`; version alone cannot distinguish them. Inspect the selected
console script and its distribution's entry-point metadata for
`loops_min.main:main`. An isolated test installation is not a live switch.

This is not legacy command-line compatibility. Source collection remains the
programmatic `sdk.run_sources()` operation; CLI `sync` only synchronizes derived
indexes. No CLI command executes source collectors or detached boundary jobs.
SDK dispatcher parameters and defaults are unchanged: without a dispatcher,
boundary run intents remain `not-requested`.

Legacy DATA migration/provenance remains the offline, signer-injected
[`migrate` API and repository scripts](../../libs/migrate/README.md), not an SDK
operation or a replacement `store migrate` verb. Preserve original archives;
preparation, migration, adoption, and live publication are separate gates. The
client has no presentation, storage, migration, or legacy CLI dependency.

For a complete fresh-store example with tested commands, see
[A fresh Loops store for Atlas observations](../../docs/guides/atlas-greenfield-cli.md).

The global `--pretty` option may appear before or after a command. Argument
errors also use the JSON envelope and exit with status 2. A built-root-wheel
smoke installs the root wheel in a clean environment and exercises all three
aliases against a temporary Arrival store; no repository checkout is needed at
runtime.

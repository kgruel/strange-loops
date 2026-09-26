# loops-min

`loops-min` is the transitional JSON process client for the headless `sdk`
package. It provides descriptor/read operations, verification, projection and
search maintenance, exact export, explicit restore-forward, and a mapped-only
Arrival writer surface. Empty-receiver import, admission, a generic replicate
command, and legacy writer retirement remain later work.

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

`emit` and `preview` require exactly one of `--payload-json STRING` or
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
fields to the SDK, retaining its existing defaults and coercion rules. The
client does not retry unknown outcomes; stable IDs and the SDK's returned
evidence are the reconciliation boundary.

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

The executable is deliberately named `loops-min` while the legacy `loops`
application remains in the workspace. The root distribution also installs the
same `loops-min` console entry point; `sl` and `loops` remain legacy aliases.
It has no presentation, storage, or legacy CLI dependency.

For a complete fresh-store example with tested commands, see
[A fresh Loops store for Atlas observations](../../docs/guides/atlas-greenfield-cli.md).

The global `--pretty` option may appear before or after a command. Argument
errors also use the JSON envelope and exit with status 2. A built-wheel smoke
can be run from a clean environment by building `loops-min`, installing it
alongside the local SDK dependency wheels, and invoking `loops-min --help` and
one temporary Arrival `summary`; the package does not require a repository
checkout at runtime.

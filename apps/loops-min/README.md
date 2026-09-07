# loops-min

`loops-min` is the transitional JSON process client for the headless `sdk`
package. It provides descriptor/read operations, verification, projection and
search maintenance, exact export, explicit restore-forward, and a mapped-only
Arrival writer surface. Empty-receiver import, admission, a generic replicate
command, and legacy writer retirement remain later work.

Writer commands require all of `--credential-root`, `--credential-namespace`,
and `--receipt-observer`. They never select locator-derived credentials or fall
back to a legacy writer or create keys. The founding binding must be
pre-provisioned for `init`; pre-provision every author and receipt binding used
by a signed workflow. Selecting the mapped provider does not make every domain
mandatory: an absent optional signer retains the SDK's unsigned behavior under
the captured declaration and signed-era rules. Callers should inspect each
result's `signed` and `witnessed` evidence. Create or import bindings explicitly
with the SDK's `MappedCredentialProvider`. For example,
`MappedCredentialProvider(root, namespace="tenant",
receipt_observer="alice").create_binding("alice", token="setup-alice")`
prepares the founding binding used by `init`.

`init` always requests an Arrival file target and never uses `init_vertex`'s
legacy default. A minimal lifecycle is:

```text
loops-min init app.vertex --name app --location /data/app.arrival \
  --observer alice --credential-root /keys --credential-namespace tenant \
  --receipt-observer alice --strict
loops-min emit app.vertex item --payload-json '{"value":1}' --observer alice \
  --credential-root /keys --credential-namespace tenant --receipt-observer alice
loops-min emit-batch app.vertex --facts-json '[{"kind":"item","payload":{"value":2},"observer":"alice","id":"item-2"}]' \
  --credential-root /keys --credential-namespace tenant --receipt-observer alice
```

`emit` requires a JSON object payload. `emit-batch` requires an array of JSON
objects and passes their observer, ID, timestamp, origin, and admission fields
to the SDK, retaining its existing defaults and coercion rules. Transport JSON rejects duplicate keys and non-finite
numbers before credential resolution. The client does not retry unknown
outcomes; stable IDs and the SDK's returned evidence are the reconciliation
boundary.

`declaration target.vertex --proposed-file next.vertex --observer alice ...`
passes the file's text to the SDK's captured declaration-edit protocol. If an
edit reports an intent after a durable interruption,
`declaration-recover INTENT` resumes it without resolving credentials again.
Initialization recovery and credential creation are not CLI commands in this
slice.

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
ceremony refusal; and 6 means custody committed or may have committed. Status
4 does not by itself prove zero derived or publication effects. Status 6 is
not permission to retry: the JSON error retains commit, IDs, intent, and
outcome evidence supplied by the SDK.

The executable is deliberately named `loops-min` while the legacy `loops`
application remains in the workspace. It has no presentation, storage, or
legacy CLI dependency.

The global `--pretty` option may appear before or after a command. Argument
errors also use the JSON envelope and exit with status 2. A built-wheel smoke
can be run from a clean environment by building `loops-min`, installing it
alongside the local SDK dependency wheels, and invoking `loops-min --help` and
one temporary Arrival `summary`; the package does not require a repository
checkout at runtime.

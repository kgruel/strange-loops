# loops-min

`loops-min` is the transitional JSON process client for the headless `sdk`
package. It provides descriptor/read operations, verification, projection and
search maintenance, exact export, and explicit restore-forward. Other custody
writers and empty-receiver import remain pending the final SDK cutover.

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

The executable is deliberately named `loops-min` while the legacy `loops`
application remains in the workspace. It has no presentation, storage, or
legacy CLI dependency.

The global `--pretty` option may appear before or after a command. Argument
errors also use the JSON envelope and exit with status 2. A built-wheel smoke
can be run from a clean environment by building `loops-min`, installing it
alongside the local SDK dependency wheels, and invoking `loops-min --help` and
one temporary Arrival `summary`; the package does not require a repository
checkout at runtime.

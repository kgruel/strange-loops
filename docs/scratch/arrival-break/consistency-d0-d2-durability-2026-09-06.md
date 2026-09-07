# D0/D2 directory durability follow-up

After the completed-slot review accepted the recovery correction, root inspected
directory publication ordering and Terra confirmed a remaining durability gap.
`_directory(create=True)` created directories without syncing their parents.
Syncing a private key or a linked intent file and its containing directory does
not by itself guarantee a newly created ancestor directory entry survives power
loss. This affects a new provider root, its schema subdirectories, and opaque
key-reference directories. The earlier interruption tests exercised process
interruptions, not loss of unsynced directory entries.

The correction must ensure directory entries are synced before dependent durable
publication, including retry after mkdir succeeds but parent sync is interrupted.
Reads must stay free of directory creation and repair. The provider retains the
same POSIX filesystem scope, complete-file publication, advisory serialization,
explicit mutation APIs, and refusal behavior. Focused tests should check actual
sync ordering and interruption/retry without claiming to emulate power loss.

This is an additional root finding; the prior Fable ACCEPT remains valid for its
completed-slot scope. Final acceptance of D0/D2 waits for this narrow correction,
affected validation, and another Fable-low review. No live state, commit, or push.

## Additional retry probe

The initial directory correction passed 79 custody tests. Root then injected
failure after linking a binding but before syncing `bindings-v1`. Creation
reported `BindingMutationIncomplete` at `binding-published`. Retrying returned
success without syncing that directory (`link-sync-probe-before.txt`). Existing
file visibility cannot prove that its prior publication was synced. Explicit
mutation retry/recovery must reconcile that durability before reporting success,
while validating contradictory retained evidence before any repair. Read-only
resolution remains outside that repair path.

## Implemented correction and validation freeze

Directory creation now fsyncs the lexical parent chain, including already
present ancestors on retry. Provider-owned targets remain lstat-validated;
trusted existing parent aliases retain their previous configured-root behavior.
After retained content validates, explicit mutation retry/recovery also fsyncs
required binding, key, pending and indexed-intent directories before completion.
Existing publication paths validate equality before syncing a prior link.

The final isolated full custody run passed **80 tests / 0.48s**, with raw output
in `custody-durability-final.txt`. Four additional regressions cover directory
ordering, nested ancestor interruption/retry, key-reference interruption/recovery,
and linked binding interruption/retry. Root’s same standalone link-sync probe
now reports `binding directory synced on retry: True`. Scoped Ruff and whitespace
checks pass. This evidence checks fsync calls and ordering, not actual power-loss
simulation. Engine/SDK production remains unchanged from its measured runs.

The patch is frozen for focused Fable-low review; final primary triage follows.

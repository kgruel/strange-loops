# C7 independent audit: bounded declaration inspection

This audit checks the C7 contract against the current implementation in the
shared worktree. The inspection operation is a root declaration inspection;
it must not become an aggregate member read or manufacture a global aggregate
head.

## Source-backed acceptance conditions

`sdk.declare.inspect_declaration` now uses the shared
`sdk.target._arrival_definition(..., allow_aggregate=True)` parser and calls
`sdk.read._arrival_declaration(..., allow_aggregate=True)` while one
`_open_arrival_read` context is held (`declare.py:692-737`). This is the right
shape: the root earns one attested CURRENT basis, while the effective
declaration is reconstructed from that root snapshot. The inspection path
does not call `open_aggregate_read`, `capture_aggregate`, member resolution,
or glob expansion. A missing or malformed child therefore remains outside
this operation's I/O surface.

The target resolver keeps the opt-in narrow (`target.py:62-95`). All other
callers retain the default aggregate refusal. Explicit role validation occurs
before the aggregate policy and before registry open (`target.py:83-94`), so a
missing role is a configuration refusal rather than a member-basis refusal.
An unknown backend still reaches the supplied registry and cannot fall through
to legacy probing.

The effective and local topology fields are literal root evidence: ordered
combine names/aliases and the discover pattern (`declare.py:857-870`,
`types.py:983-986`). They do not claim member existence or a shared aggregate
basis. This preserves both topology disagreement directions: local aggregate
/effective plain and local plain/effective aggregate. The root basis remains
the only `basis` in the result.

The storeless aggregate branch is now before `probe_target` and
`load_declaration_status` (`declare.py:739-760,803-841`). It retains one parsed
AST, returns `read_path="local-frozen"`, no store/basis, and creates detached
topology/fingerprint evidence. This prevents legacy probing from opening a
replacement or unrelated store and makes later source-file mutation unable
to mutate the returned result. Plain storeless legacy declarations remain on
the compatibility path by design.

`_open_arrival_read` closes the returned `OpenedRead` in its `finally` block
(`read.py:95-115`); `OpenedRead.close` is idempotent and quiet for snapshot,
query, and ledger resources (`arrival_consumer.py:52-111`). Thus effective
declaration failures still release the one root open. No member resource is
created or needs closing.

## Acceptance evidence and disposition

The independent contract file exercises both topology disagreement directions
through an opaque registry. It observes exactly one root open and query/ledger
closure on success and effective-declaration refusal. A poisoned `Path.glob`
proves discovery is not expanded. Snapshot closure is source-reviewed through
`OpenedRead.close`, rather than separately instrumented in the tests.

The storeless discover test poisons both legacy probe and declaration loader.
Missing role and unknown backend tests poison legacy fallback. Existing
inspection tests retain CURRENT absent/behind refusal with custody/index byte
preservation; owner tests add aliases, file-replacement detachment and legacy
stored-aggregate compatibility. JSON serialization covers the independent
results and storeless combine result. Null topology and nonempty ordered
combine entries are exercised; the parser forbids an empty local combine, so
there is no claim of a public empty-combine integration test.

Final focused independent validation, from `libs/sdk`:

```text
uv run pytest -q tests/test_arrival_inspect_contract.py
5 passed in 0.19s
```

Final package validation and the early unisolated test-run disclosure are in
[the validation report](consistency-c7-validation-2026-09-06.md). Engine source
is unchanged by this slice.

## Limits and compatibility boundaries

This slice does not validate aggregate entity/fact semantics, member custody,
aggregate state/fold behavior, topology validity, credential mapping, or
legacy retirement. Opening an aggregate read remains the operation that may
resolve members and require per-member evidence. Inspection can report a
declared child that does not exist. Attestation/witness advancement during
the single root open remains an established custody behavior; "inspection"
does not mean zero journal writes.

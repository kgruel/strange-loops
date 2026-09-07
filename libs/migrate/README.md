# `migrate` — Migration Sidecar

The `migrate` package transforms pre-Arrival legacy stores into a new Arrival
history. Legacy readers and codecs remain quarantined here: active runtime
packages do not import `migrate`.

The sidecar preserves source rows under the selected transform, verifies the
resulting log and row equivalence, writes a signed external report, and publishes
an explicit File descriptor with the minted lineage and `role="authority"`.
It checks that the vertex bytes captured for transformation have not changed
at publication entry and immediately before replacement. This is an offline operation on quiescent inputs; the check
is not a lock or an atomic compare-and-swap against concurrent writers.

**Publication does not adopt a declaration.** The descriptor can be resolved,
verified, and explicitly synced through the SDK. The new log still needs an
explicit declaration adoption before ordinary SDK reads, declaration edits, or
writes can proceed. Historical `_decl.*` rows are retained as migration evidence;
the current runtime does not infer the new store's identity from them or from
its locator file. The old `loops store migrate` wrapper is therefore not a
complete migration-to-current-runtime workflow.

Use isolated copies for rehearsals, with separate state/configuration and
credential roots. Keep the original stores and descriptors untouched. SQLite
copies must come from quiescent inputs or a coherent database snapshot.

The exported `edit_vertex_store_clause` helper now requires explicit `lineage`
and `expected_original` byte arguments. Direct callers must supply the exact
vertex snapshot used for planning; `run_migration` supplies these itself. An
error after replacement (for example, directory fsync failure) can leave the new
descriptor visible. Inspect the artifacts before retrying. An exact explicit
`resume_target` can re-verify an already published migration without replacing
the descriptor. It does regenerate, re-sign, and replace the migration report;
changing `tool_version` changes that signed report. This is not a general
recovery or adoption API.

Descriptors from the previous sidecar that contain `backend="file"` but omit
lineage or role are refused by the new existing-descriptor guard. They need
explicit descriptor reconciliation before this resume path can apply; adding
those fields alone still does not adopt their declaration.

The migration report certifies the head at migration completion. Its current
verifier requires that exact live head, so verify it before a later adoption or
ordinary append advances the target. Structural Full verification without an
injected signature verifier does not establish historical authorship.

See the [publication report](../../docs/scratch/arrival-break/consistency-c9-migration-publication-2026-09-06.md)
and [adoption design](../../docs/scratch/arrival-break/consistency-c9-migration-adoption-design-2026-09-06.md).
The historical sidecar design is recorded in
[the slice 4 proposal](../../docs/scratch/arrival-break/slice4-design-proposal.md).

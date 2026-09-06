# Legacy cut: dependency extraction handoff

Status: primary's next bounded task after SDK source integration. Extract
surviving pure responsibilities before deleting old authority implementations.
This task alone neither removes a supported operation nor completes the cut.

## Direct dependencies to split

The new File adapter still imports metadata key constants and
`ArrivalCanonicalUnsupported` from `arrival_store`, plus insert SQL from
`sqlite_store`. `arrival_projection` imports `_SCHEMA_STMTS`, insertion SQL
and `ensure_coordinate_schema` from `sqlite_store`. These are valid file-
projection responsibilities housed in modules that also implement superseded
authority modes.

Move the SQLite projection schema/column vocabulary into a focused backend-
specific schema module. Preserve exact SQL and row-shape semantics; use one
definition and temporary legacy re-exports, not duplicated constant lists.
Move Arrival projection metadata keys and the relevant projection refusal to
the projection module or a small shared file-projection definition module with
an acyclic dependency direction. Do not remove an existing exception alias
until all callers and SDK error mapping are updated.

`WriteCredentials` and `CredentialProvider` are neutral runtime injection
values currently housed in the legacy SQLite-oriented `engine.handle`.
Move them to a focused neutral credentials module. New coordinators, SDK
credential providers and type-only imports should use that definition; old
handle consumers may retain a re-export during the cut. Preserve distinct
FACT and ARRIVAL signers and optional tick signer, with no default key creation.

Arrival projection still uses `jsonl_codec` for the derived compatibility log
and `residence` for file-specific path helpers. Inventory those separately:
exact wire export is the new transfer primitive, so derived compatibility-log
creation must not become another authoritative log by surviving accidentally.
Keep actual file-adapter projection paths backend-specific and legacy decoding
inside migration. Identify callers before removing either helper family.

## Validation and following deletion

Run relevant FileLedger/query/projection/runtime/SDK tests and the full
architecture suite. An import scan should show new supported coordinators no
longer importing legacy writer modules for constants or credentials. Register
new modules with existing architecture scan completeness checks as required.
Avoid whole-file reformatting of large legacy files while moving a few symbols.

Following stages route or retire `load_program`, `VertexHandle`, legacy
declaration ceremonies, probe/residence suffix selection, and store transport
entrypoints; then delete `JsonlStore`/`SqliteStore`/`ArrivalStore` as alternate
authority implementations. Projection storage remains SQLite for the file
adapter. Read-only file projection helpers can survive with an explicit adapter
boundary. Preserve meaningful primitive/fold tests by converting fixtures;
tests exclusively asserting removed authority modes should be retired with
those modes rather than keeping the production mode alive for a test.

The SDK cut must precede enabling minimal CLI writers: a CLI precheck followed
by a still-legacy-capable SDK writer is not the final supported contract.
Keep one public SDK family, make ordinary initialization Arrival by default,
refuse implicit legacy artifacts through supported operations, and use the
migration sidecar for adoption. Rich outgoing CLI presentation parity is not
required; its standalone authority routes cannot remain shipped under the
new minimal CLI's entrypoints.

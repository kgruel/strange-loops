# C7: bounded aggregate declaration inspection

## Decision

`inspect_declaration` reports the **root declaration's topology**, not an
aggregate read. A descriptor-bearing root first earns one CURRENT
`OpenedRead`; its effective declaration at that captured root H/P/G selects
whether the result is ordinary or aggregate. It never calls
`open_aggregate_read`, expands combine/discover, opens a member, or returns a
synthetic/global aggregate head.

Target resolution needs one purpose-specific opt-in:
`_arrival_definition(path, allow_aggregate=True)`, used only by inspection.
It makes one root parse and returns its AST with an optional explicit
descriptor. Inspection chooses descriptor-backed versus storeless from that
same AST; the storeless branch additionally requires `store is None`.
It does not use local `combine`/`discover` to choose a descriptor read
shape. The default single-store descriptor resolver keeps refusing aggregate
locators. An explicit descriptor with a missing role still refuses before any
open.

## Result evidence

Keep `DeclarationInspectionResult` v2 additive. In addition to the current
`is_aggregate`, expose the unexpanded effective root shape:

- `effective_combine`: ordered entries with `name` and optional `alias`,
  or null;
- `effective_discover`: the literal pattern, or null;
- `local_combine` and `local_discover` with the same form.

These are declaration evidence only. They do not assert members exist, were
opened, or form a complete topology. Existing local/effective fingerprints
continue to identify the exact parsed documents used for each view. For a
descriptor root, `read_path="arrival"`, `store`, and `basis` remain the
single root descriptor/H/P/G from the one attested read. There is no
`aggregate_members` field or aggregate Head.

For a storeless aggregate root, parse the target bytes once and construct the existing
inspection fields plus local shape/fingerprint from that AST. Return
`read_path="local-frozen"`, `store=None`, `basis=None`,
`local_status="frozen-local"`, `effective_status="local-only"`, and make
effective shape/fingerprint equal to the retained local evidence. This is
honestly local-only: it has no adopted declaration or CURRENT basis. The
fingerprint is semantic-document evidence, not a claim that an exact file byte
hash was retained. The result must retain plain detached lists/dicts/strings
so a later file edit cannot mutate the returned evidence.

## SDK route

In the explicit-descriptor branch, call
`_open_arrival_read(arrival, registry=registry)` once and, while it is open,
call `_arrival_declaration(locator_ast, path, opened, allow_aggregate=True)`.
Pass its effective AST to the existing inspection-field and topology serializers.
The local AST returned from resolver is the only local comparison input. This
preserves CURRENT refusal and registry error behavior before any legacy probe
or aggregate planner. No read-time materialization or repair is permitted.
Inspection does not write a projection, though opening a registry may perform
the established witness/attestation advancement.

For a no-descriptor stored vertex, retain current syntax/legacy handling. Only
the already parsed storeless aggregate AST takes the frozen branch; it must not
recursively inspect local children.

## Acceptance

1. Descriptor root whose local locator is aggregate but captured effective
   declaration is plain: returns one root Arrival basis and plain effective
   shape; a member-open sentinel is untouched.
2. Descriptor root whose local locator is plain but captured effective
   declaration is aggregate: returns root Arrival basis and its effective
   combine/discover evidence; nonexistent/effectively declared child locations
   do not cause opens.
3. The two results report both local and effective shapes/fingerprints, proving
   neither local direction silently selects execution topology.
4. A storeless local aggregate returns `local-frozen`, no basis/store, and
   detached unexpanded evidence. Changing the source file after return changes
   no returned value.
5. Existing explicit-role validation and missing/behind CURRENT-projection
   refusals remain before legacy fallback; an injected unknown backend remains
   an adapter refusal, not a legacy result.

This slice deliberately does not promise topology validity, member custody,
or aggregate state/fold semantics.

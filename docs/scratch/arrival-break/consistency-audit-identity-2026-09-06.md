# Identity consistency audit — 2026-09-06

## Scope and conclusion

Arrival has several deliberately separate identity namespaces. The current protocol and
implementation support a clear minimum rule: preserve each namespace explicitly and bind
them only where the contract says to. In particular, a local key is not an observer, an
observer is not a vertex, and a physical lineage is not a vertex name.

| Concept | Established contract | Current implementation / constraint | Decision status |
| --- | --- | --- | --- |
| **Observer label** | Exact, non-empty record-profile string. It selects the author key for a fact/batch; a tick envelope instead names the log custodian. Unicode has no protocol normalization. | Custody maps a label to local directory components and rejects unsafe or filesystem-alias spellings. That is local key-management policy, not a wire canonicalizer. | Established: preserve exact labels at the protocol boundary. Applications needing case/Unicode equivalence must define it before signing. |
| **Signing key and key history** | A public key is bound to an observer by genesis/key-introduction history. It is valid only after introduction; record verification uses the record's observer and a key valid at that coordinate. | `custody.signing` locates/mints local private keys and supplies domain-separated fact, tick, and Arrival signers. `sign.ed25519` is a crypto utility, not an identity authority. | Established: no inference that key bytes equal observer identity. A missing local key may yield unsigned work where the operation permits it; ambiguity/collision must refuse. |
| **Vertex declaration name** | A declared, human-meaningful declaration identity. Post-genesis vertex-name change is already treated as an explicit ceremony rather than a routine reabsorb. | `VertexFile.name` drives declaration facts and tick origins in the current program. `ObserverDecl.identity` is a declaration-language field, not an Arrival key-history binding. | Established separation from observer and lineage. Keep rename policy explicit. |
| **Vertex path / descriptor location** | The `.vertex` path is residence/ingress; backend location is an operational adapter address. Neither belongs in absorbed declaration identity. | Custody currently uses the vertex filename stem only to find the local self key. Registry checks the descriptor's claimed lineage after opening. | Constraint: changing a locator can affect local key discovery, but must not silently rename a wire observer or vertex. |
| **Physical lineage** | `Head.lineage` identifies one physical custody history. Genesis body lineage equals envelope lineage. | In an adopted Arrival projection, the licensed own declaration genesis fact has `id == Head.lineage`; `store_meta.own_lineage` records that binding. | Established anchor invariant, not an equation of lineage with vertex or observer. |
| **Aggregate member** | Composition identity is an occurrence in the topology, not a store/lineage. Repeated occurrences of one lineage are meaningful. | `OccurrenceIdentity` includes path, locator, declaration identity, and role; each member retains its own basis and frozen definition evidence. | Established current aggregate policy: no same-lineage collapse and no fabricated common head. |
| **Loop and vertex boundary** | A tick body carries one `name`; its envelope observer is the physical-log custodian. | Loop ticks represent one loop state; vertex ticks represent the vertex boundary/full state. Current replay/planning keys boundary ownership by names and captured declaration semantics. | Needs an explicit continuity decision for loop/boundary renames; current tick wire evidence has no separate durable boundary ID. |

## Evidence and implications

### Observer labels, signing material, and history

The wire format assigns `observer` different *roles* by record kind: fact/batch author,
tick-log custodian, and genesis/key founding or introducing identity
([wire-format.html](../../architecture/arrival/wire-format.html), records and key-history
sections around lines 157–166 and 202–279). Fact and batch inner/outer signatures are
verified against the row author's historical keys. A tick's body `name` is a boundary
name, while its outer envelope observer is deliberately the destination log's genesis
observer and the tick envelope is unsigned. The outer Arrival signature commitment
contains kind, time, observer, origin, and body, but not custody coordinate
(lines 332–342).

`KeyRegistry.keys_valid_at` and `verify_authorship` implement the introduction-before-use
rule in [arrival.py](../../../libs/engine/src/engine/arrival.py) (around lines 1901–1995).
Tests cover genesis self naming and body-lineage agreement in
[test_arrival_grammar.py](../../../libs/engine/tests/test_arrival_grammar.py) (around
lines 225–254 and 304–312). This establishes an observer-to-public-key-history relation;
it does **not** establish a key-to-vertex or key-to-lineage relation.

Custody's local directory and filename rules in
[signing.py](../../../libs/custody/src/custody/signing.py) (roughly lines 39–183) are
therefore an implementation boundary. They appropriately reject aliases, ambiguous
self-key layouts, unsafe components, and damaged state rather than borrowing a key.
They must not normalize the observer sent to Arrival. This matches
[libs/custody/CLAUDE.md](../../../libs/custody/CLAUDE.md): custody owns local private-key
layout and signer providers; the engine owns no such layout.

**Concrete configuration inconsistency to decide:**
`CustodyCredentialProvider.__init__` stores `key_dir`, but `for_write` invokes
`tick_signer_for`, `fact_signer_for`, and `arrival_signer_for` without it
([sdk/emit.py](../../../libs/sdk/src/sdk/emit.py), lines 92–104). Those custody functions
currently take a vertex path rather than a key root. The parameter consequently does not
select keys. Decide one small direction: either remove/deprecate the ineffective SDK
parameter, or introduce an explicit injected custody locator/provider used consistently
for public-key registration and all three signer domains. Do not use it to derive an
observer, vertex name, or lineage.

### Vertex, locator, declaration, and physical lineage

After adoption, a declaration file is locator plus ingress cache; effective declaration
facts from the bounded projection are canonical
([declaration.py](../../../libs/engine/src/engine/declaration.py), lines 1–60 and
820–879). The language document loader likewise treats path, store, backend, and location
as externally supplied residence rather than signed declaration content
([document.py](../../../libs/lang/src/lang/document.py), lines 890–909). `VertexFile.name`
is a declaration identity; changing it after genesis is explicitly refused as an ordinary
reabsorb (around lines 1075–1078 and 1141–1147). None of those rules makes filename stem,
descriptor location, or vertex name an observer alias.

The physical binding is narrower. `licensed_own_lineage` requires a consumed
`_decl.genesis` fact whose id equals the physical Arrival lineage
([arrival_projection.py](../../../libs/engine/src/engine/arrival_projection.py), lines
423–449). The consumer and runtime capture validate that anchor on the same bounded
snapshot ([arrival_consumer.py](../../../libs/engine/src/engine/arrival_consumer.py),
lines 140–214; [runtime_write.py](../../../libs/engine/src/engine/runtime_write.py),
lines 720–843). Tick custody then comes from verified physical record zero, not a locator
or vertex name (runtime_write around lines 947–955).

**Minimum rule:** returned evidence should keep `Head`, `DeclarationAnchor`, descriptor,
and declaration identity as separate typed values. The supported-adoption invariant is
`anchor.own_lineage == anchor.genesis.id == Head.lineage`; it does not make any of those
strings a vertex name or an observer.

### Aggregate occurrence identity

Aggregate capture intentionally treats `(occurrence path, locator, declaration identity,
role)` as a member identity. It retains an independent `ReadBasis` and frozen effective
definition for each occurrence, including repeated same-lineage members
([arrival_aggregate.py](../../../libs/engine/src/engine/arrival_aggregate.py), lines
56–145 and 261–345). Tests explicitly retain two occurrences of the same lineage and
show structural ordering independent of matching-row/observer filters
([test_arrival_aggregate.py](../../../libs/sdk/tests/test_arrival_aggregate.py), lines
126–145 and 288–320).

This is an established composition choice worth preserving: report provenance per
occurrence, retain shadowed own-overlay captures as evidence, and never create an
aggregate cursor, watermark, or attestation by comparing member ordinals across lineages.
Deduplication, if a later fold wants it, is a fold semantic and must name its key.

### Boundary identity and declaration continuity

`Loop.fire` emits ticks named for the loop with vertex origin; a vertex boundary emits a
tick named/originated by the vertex ([loop.py](../../../libs/engine/src/engine/loop.py),
lines 145–166; [vertex.py](../../../libs/engine/src/engine/vertex.py), lines 882–965).
The pending-boundary planner restores period/count/window context from bounded facts and
ticks and owns only its ticks (vertex.py around lines 1260–1350). Compiler declaration
order and names determine the corresponding specs
([compiler.py](../../../libs/engine/src/engine/compiler.py), lines 559–604 and 780–800).

A CURRENT capture fixes declaration and custody evidence before planning; a later
declaration cannot rewrite the captured operation, and CAS rejects a stale append
([test_runtime_capture.py](../../../libs/engine/tests/test_runtime_capture.py), lines
56–111). That is sufficient for one operation, but the tick wire row lacks a declaration
revision or separate boundary UUID.

**Decision needed:** choose whether a loop-name/boundary-semantic declaration change is
(a) refused unless accompanied by an explicit continuity/migration ceremony, or (b) an
intentional semantic discontinuity, with historical ticks interpreted under their
captured declaration and new ticks under the new one. Do not imply automatic continuity
or rename mapping without new durable evidence. This decision can be deferred without a
wire migration, but code and public documentation should not promise more than captured
semantics today.

## Minimum bounded decisions

1. Publish the namespace separation above in the public contract/result vocabulary:
   observer label, public-key history, vertex declaration identity, locator/descriptor,
   physical lineage, aggregate occurrence, and boundary name each have distinct meaning.
2. Select the `CustodyCredentialProvider.key_dir` disposition: delete/deprecate it, or
   replace it with one explicit custody-provider/key-locator abstraction. Its present
   behavior is misleading configuration, not a protocol migration.
3. Adopt one explicit loop/boundary declaration-change continuity policy before exposing
   rename or edit behavior as stable. The conservative first policy is refusal for
   identity-bearing boundary renames and captured-declaration semantics for ordinary
   edits.
4. Keep the current aggregate provenance rule: repeated same-lineage occurrences remain
   distinct, member bases remain per occurrence, and no aggregate common head is claimed.

None of these decisions requires rewriting stored Arrival records. A wire migration is
only necessary if the project later needs a versioned durable boundary identity or a
protocol-level observer-equivalence rule.

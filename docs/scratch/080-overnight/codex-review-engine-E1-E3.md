1. **MAJOR** — `libs/engine/src/engine/vertex_reader.py:961`  
   `vertex_fold(at=...)` never verifies that `at.lineage` matches the target store. It later applies `at.rowid` directly at line 1038. A `WitnessPosition` resolved against adopted store A can therefore be passed to store B and silently select an unrelated prefix, violating the lineage-qualified-handle contract.

2. **MAJOR** — `libs/engine/src/engine/declaration.py:295`  
   The independent receipt-group guard is bypassed when no own genesis exists, because the function returns before the guard at lines 341–354. It is also bypassed for positions preceding genesis by the early `Unhistorized` return at line 335. Thus a hand-built mid-group `WitnessPosition` can reach `resolve_declaration_documents(at=...)` without refusal in pre-genesis/imported-history cases, contrary to the required unconditional engine-selector guard.

3. **MAJOR** — `libs/engine/src/engine/vertex_reader.py:539`  
   Combined tick envelopes identify their source using only `path.stem`. Distinct member stores such as `a/events.db` and `b/events.db` both become `"events"`, leaving consumers unable to determine which store should resolve the passed-through `fact_cursor`. The E3 envelope is therefore not reliably member-attributable for valid aggregate topologies.

4. **MINOR** — `libs/engine/src/engine/declaration.py:444`  
   `load_declaration_status()` does not enforce `as_of`/`at` mutual exclusion itself. Storeless aggregates, missing stores, and file-pre-genesis paths return at lines 447–458 before reaching `resolve_declaration_documents()`’s check. Consequently the public dual-selector API accepts both arguments depending on store state.

5. **MINOR** — `libs/engine/src/engine/witness.py:212`  
   `_resolve_anchor()` orders only by the referenced fact’s `rowid`. Multiple ticks can seal the same unchanged `fact_cursor`; ties are then nondeterministic, so the returned `TickAnchor.name` and `ts` need not describe the last sealed tick as documented.

The focused tests could not execute because the read-only environment provides no writable temporary directory. Static inspection found the fold replay itself correctly selects with `rowid <=` and replays with `ORDER BY ts, id`; the single-store tick path remains structurally unchanged.
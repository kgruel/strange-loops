# Synthetic Arrival baseline

These are single-run development measurements on this machine, not realistic
workload or release performance acceptance. Both use a temporary default SDK
initialized target, real custody signatures, one same-observer batch, item
payloads containing URL/title and about 256 characters of text, then one
`read_facts(limit=50)` call. Temporary stores and keys are removed afterward.

| Facts offered | SDK batch seconds | First page seconds | Rows returned |
| --- | ---: | ---: | ---: |
| 100 | 0.0586 | 0.0079 | 100 |
| 1,000 | 0.3847 | 0.0541 | 1,000 |

The baseline exposed a paging contract mismatch: FileQuery expands the last
Arrival ordinal to all of its fact rows, despite the public SDK describing
`limit` as a maximum number of facts. Its continuation currently skips that
whole ordinal. This is implementation intent, not a rule in the ratified query
proposal or Arrival backend contract.

Primary decision: change fact pages to a hard row maximum and resume by the
existing `(arrival_ordinal, arrival_seq, id)` cursor. A page remains a subset
of one captured H/P; it does not assert a new custody prefix inside the batch.
Ledger scans/exports and historical declaration transitions retain atomic
record semantics. The bounded continuation already carries H, P and view
generation, so presentation may split rows without creating a partial ledger.
Terra will implement this as a separate follow-up after SDK verification.

The earlier known O(prefix) projection generation digest still applies. These
small batches do not demonstrate cheap large-store pagination, nor do they
test a process per command, aggregates, source execution or realistic history.
Repeat the page baseline after the hard-limit correction and use representative
copies during the later acceptance stage.

## After the hard-limit correction

Same temporary workload, measured once per size after the correction:

| Facts offered | SDK batch seconds | First page seconds | Rows returned |
| --- | ---: | ---: | ---: |
| 100 | 0.0441 | 0.0062 | 50 |
| 1,000 | 0.3648 | 0.0497 | 50 |
| 10,000 | 6.2701 | 0.4961 | 50 |

The 10,000-row first-page cost confirms that hard output limits do not make
snapshot acquisition cheap. Full ledger walks and the complete projection
generation digest remain measurable costs. Before realistic adoption, profile
those separately and decide how the file adapter can prove stable bounded view
identity more cheaply while retaining the accepted continuation tests (later
appends preserve old H/P; changing old projected rows invalidates the token).
Merely deleting the digest or replacing it with the watermark would weaken the
current contract. No such optimization is implemented by this baseline.

## Profile of the 10,000-fact packed batch

Primary ran cProfile around just the first 50-row SDK read of another
temporary, signed 10,000-fact batch. Profiling adds substantial overhead:
the instrumented call took 1.778 seconds and is not directly comparable to
the uninstrumented table above. It made about 10.8 million calls.

The dominant cost in this particular shape is repeated canonical decoding of
the large tail record, not projection row hashing: six `decode_record` calls
accounted for 1.718 cumulative seconds, with 1.676 seconds under RFC 8785
canonicalization. Two `verify(Open())` calls took 1.175 seconds; completing
the projection watermark with `head_at` added 0.556 seconds. These cumulative
times overlap and must not be added. Snapshot setup and query processing
outside custody decoding accounted for much less of this sample.

The first Open check pins descriptor lineage before first-contact witnessing;
the second belongs to the attested opener. The watermark lookup separately
proves prefix membership. Any optimization must preserve these claims and
binding/replacement checks, rather than merely cache an unvalidated pathname
or skip a structural check. A many-small-record workload is still needed to
separate prefix-walk cost from large-batch canonicalization. No performance
optimization was made during this profile.

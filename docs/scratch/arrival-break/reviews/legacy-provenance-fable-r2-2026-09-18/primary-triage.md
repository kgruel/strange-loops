# Second review: test-only corrections

Fable accepted the verifier, receipt wording, cutover plan and engine-generated
integration. It returned a narrow REVISE because four refusal tests stopped at
neighboring checks rather than the checks named by the tests. No production
verifier change was requested or made after this review.

Luna corrected those cases:

- A bad post-S window now has the actual last predecessor and continuous valid
  cursors, and requires the precise post-migration window-mismatch refusal.
- The missing transformation case has two eligible rows, one actual mapping and
  one missing audit entry, and requires the eligible-row refusal.
- The reversed window preserves start continuity and uses an earlier end cursor,
  requiring the reversed-window refusal.
- Mutated and reordered source prefixes are re-minted with valid Arrival hash
  chains and repinned S, requiring exact-prefix-row refusal. Separate corrupt
  wire-order/torn-tail checks remain.

Provenance suites now pass 31 tests; the final repository run passes 163 tests
(excluding chaos). Production source remains exactly the reviewed verifier.

Small plan clarifications distinguish source SHA-256 from original/candidate
vertex SHA-256 variables, bind the at-A provenance receipt to A and its store
hash for rollback, record excluded-command disablement, and show the affected
row count for the fresh production snapshot. Publication remains an illustrative
algorithm pending completion/rehearsal, not an executed live operation.

A final bounded test-diff review is archived separately.

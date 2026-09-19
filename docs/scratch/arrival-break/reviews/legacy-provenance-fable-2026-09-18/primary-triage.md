# First review and correction record

Fable returned REVISE: no P1 or constructed false pass in the mapping checks,
but five P2s required correction. It closed the prior fresh-epoch rehearsal tick
attestation finding. The native review and source packet are retained.

The only source drift during that first review was `_hex(value: str, ...)` to
`_hex(value: object, ...)`, a type annotation matching its existing runtime type
check; the exact delta is archived. The second packet contains final source.

1. **Historical unchained links:** permit only a pre-chain era without claimed
   predecessor/cursor fields; refuse a return to unchained history after chaining.
   Emit the unchained count. The loops copy has zero such ticks.
2. **Receipt claims:** describe pins as caller-supplied, with independent origin
   unverified by the tool. Distinguish structurally verified chain checks from
   ordinary envelope/inner signature authentication, which is not claimed.
   Registry-forming signatures are verified throughout the stream, including
   post-S key introductions; a forged introduction now has an explicit negative
   regression.
3. **Refusal and integration coverage:** Luna added independent tests for pin,
   manifest, identity, cursor, prefix, tail, post-S tick and key-introduction
   failures. The integration uses the preparer and actual SDK fresh seal writer,
   then verifies through its new tick and checks that all four inputs and the
   directory listing remain unchanged. Combined provenance tests: 29 passed.
4. **Legacy CLI gate:** the cutover plan states that refusal is unverified across
   the legacy commands. Disablement, not assumed fail-closed behavior, protects
   the candidate and live store until reviewed adapters replace those consumers.
5. **Rollback proof:** under stopped writers, rollback before new writes requires
   exact A coordinates and store hash, candidate vertex hash and original source
   hash, followed by staged/fsynced restore. Otherwise only forward recovery is
   allowed.

Additional small hardening: hash and parse the same manifest bytes, refuse signed
blank observers and unexpected flat fields, compare observer-only row tuples,
close stream generators, and sanitize unexpected CLI failures. The full repository
suite passes 161 tests (excluding chaos). The corrected real-copy run still
accounts for 982 mapped facts, 39 explained historical windows, 82 unchanged
windows, and one valid post-S tick. The standard deep audit was not changed.

The final follow-up review is archived separately; this record does not claim its
outcome in advance.

# D0/D2 implementation review — primary triage

Fable-low returned **ACCEPT** on frozen packet
`1edcdb938b9676779eefc3b9b6246ca50e4e7565cd76f619e2ca56a8c7aaaa05`.
Primary disposition is **REVISE**: two independent executable counterexamples
contradict the review's stated recovery/publication conclusions. Passing tests
and the external verdict do not override these observed correctness failures.

## Required corrections

1. **Published binding contradicts retained intent.** Create Alice and Bob with
   distinct valid managed keys. Replace Alice's slot's ref/public with Bob's
   while retaining Alice's namespace/observer. `create_binding` refuses, but
   `recover_binding(alice, original_token)` returns Bob's binding. The published
   shortcut validates material but does not compare it with the pending/token/
   completion evidence. Recovery must compare exact identities/ref/provenance
   and pinned public material before returning. Missing completion is a valid
   crash window, but a conflicting completion is not.
2. **Pending publication precedes token-index publication.** Interrupt between
   those two links. Recovery succeeds without restoring the token index. A
   second observer using the same token can publish its own binding before a
   completion conflict raises. The original token must remain reserved even
   with only its pending marker present. Under the existing provider lock,
   inspect pending token ownership before any new publication and reconcile
   the exact token index on both create retry and recovery.

Root scripts and results are retained in validation evidence. The four new
independent regression cases cover contradictory published recovery and the
pending/index gap before recovery, after create retry, and after recovery.
Terra owns the minimal production correction; root owns independent regressions.
Full custody and a focused Fable-low follow-up review are required.

## External notes

The remaining notes are non-blocking and do not authorize unrelated changes.
The current declaration's receipt-key policy is deliberate; corrupt unrelated
bindings may conservatively refuse explicit existing-ref reuse. Initialization
recovery signs nothing and does not assert present signing readiness. Retained
pending records are recovery evidence, not a list of unfinished operations.
The follow-up should verify these scope statements without claiming every
partial state is correct from the prior ACCEPT.

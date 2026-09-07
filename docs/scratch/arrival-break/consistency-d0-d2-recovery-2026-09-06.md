# D0/D2 recovery follow-up

Status: corrective implementation validated; focused Fable-low review pending.
This follows the [primary rejection of the first implementation review's
ACCEPT](reviews/consistency-d0-d2-implementation-2026-09-06/primary-triage.md).

## Observed failures

Root executed the frozen implementation against two independent counterexamples:

- Alice and Bob each had valid managed keys. Substituting Bob's ref/public in
  Alice's published slot made create retry refuse, but recovery returned Bob's
  key under Alice's original token. Material validity alone did not establish
  consistency with the retained intent.
- A process interrupted between pending-slot and token-index publication left
  a reserved token without its index. Recovery failed to restore that index.
  A second observer using the same token could publish a binding before its
  completion conflict raised (binding count changed from one to two).

The raw Fable ACCEPT remains archived. It was insufficient evidence to complete
this slice; root's primary verdict was REVISE based on executable failures.

## Correction

Provider mutations already share one lock. Within it, pending records now
reserve their token even if the token index was not published. Creation retry
and recovery compare exact pending/index ownership and reconstruct a missing
index only from the matching retained intent. A different slot's use of that
token refuses before publishing another binding.

Published recovery checks namespace, observer, key reference, provenance,
pinned public material when present, token-index content, and any completion
record against the retained intent. A legitimate missing completion can be
published after validation; contradictory evidence refuses. Completed create
retry also checks retained pending evidence rather than relying only on a
possibly missing token index.

Unexpected recovery failures during mutation retain BindingMutationIncomplete
coordinates (namespace, observer, token, key reference, phase). Process-control
BaseExceptions retain identity. No cleanup, migration default, wire change, or
engine/SDK production change is part of this follow-up.

## Validation

- Root reran both standalone probes: both create/recover refuse substituted
  intent evidence; the interrupted-index probe recovers Alice and refuses Bob
  with binding count unchanged at one.
- Four root regression cases cover substituted recovery and the token/index
  gap before recovery, after creation retry, and after recovery.
- Terra added three provider cases, including the combined missing-index plus
  substituted-slot state and a failure after recovery publication.
- Terra's isolated full custody suite: **74 passed** (agent tool execution;
  original terminal result, no separate raw log captured).
- Root's full SDK suite against the corrected provider: **578 passed / 22.17s**.
- Prior full engine **2,611 passed, 1 skipped**, sign **40 passed**, and
  architecture **101 passed** remain applicable: their production code did not
  change in this follow-up.

Only custody/binding.py and its two test files changed from the first
implementation-review source freeze. Root compared source hashes. The normal
SDK suite and all probes used isolated XDG state/config and LOOPS_HOME.

## Independent native audit

Luna independently ran the 24 focused provider/recovery tests and source-audited
the correction. It confirmed both blocking counterexamples are fixed. It also
observed that explicit recovery can restore a missing token index from a valid
retained pending intent before refusing a candidate with public material but
no private key. Root treats that as a permitted partial metadata repair: it
creates no key or binding, overwrites no prior evidence, and makes no completion
claim. Recovery is an explicit mutation operation; read resolution still creates
nothing. This is not a blanket zero-filesystem-effect refusal guarantee, and the
focused reviewer should challenge this distinction if it breaks a stated
contract. The observed refusal remains a candidate error; no private key is
invented to continue.

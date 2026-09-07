# Primary triage: C9 setup initial review

Verdict: **REVISE**. Fable B1 is accepted. Custody `_read_json` and pending
identity validation can raise TypeError. The SDK catches only OSError and
ValueError after entering a lifecycle mutation, so malformed persisted JSON
can escape without request coordinates as CLI status 70. Add TypeError to
that specific classification boundary and test actual malformed evidence,
including preserved request coordinates and unknown phase. Keep process-control
exceptions and unrelated unexpected exception families unchanged.

The initial frozen packet is preserved. A separate correction review will
close this blocker after regression and appropriate validation. Optional
remarks about conservative outcomes and DTO concrete-type compatibility are
already documented. Absent legacy-import candidate recovery coverage is useful
but is not a blocker or a reason to alter the custody protocol.

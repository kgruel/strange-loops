# Stage E site inventory — explorer e4 (flash-low, HEAD 560710b8)

found

- `libs/engine/src/engine/canonical_audit.py:79-121` — The Check dataclass definition and its beyond_offset field.
- `libs/engine/src/engine/canonical_audit.py:340-353` — The index check in audit_agreement opening index and recording Check("index", ...).
- `libs/engine/src/engine/canonical_audit.py:383-428` — _suffix_unindexed function and rewound-marker / unindexed-corroboration docstring.
- `libs/engine/src/engine/canonical_audit.py:430-461` — _check_offset implementation.
- `libs/engine/src/engine/canonical_audit.py:464-492` — _check_counts implementation.
- `libs/engine/src/engine/canonical_audit.py:495-543` — _check_last_line implementation.
- `libs/engine/src/engine/canonical_audit.py:284-310` — _last_line backward byte-scan implementation.
- `libs/engine/src/engine/canonical_audit.py:605-704` — _deep_checks implementation.
- `libs/engine/src/engine/arrival.py:1120-1179` — _anchor_for validation and self-consistency comment.
- `libs/engine/src/engine/arrival.py:1206-1238` — walk_marked implementation.
- `libs/engine/src/engine/arrival.py:1180-1194` — _record_ending_at implementation.
- `libs/engine/src/engine/arrival.py:1040-1053` — ArrivalLog.read and walk walking from zero.
- `libs/engine/src/engine/arrival.py:680-683` — ResumeMark.arrival_ordinal definition.
- `libs/engine/src/engine/arrival_projection.py:343-370` — audit_derived_log implementation.
- `libs/engine/src/engine/arrival_projection.py:313-341` — _derived_digests implementation.
- `apps/loops/src/loops/commands/store.py:122-164` — canonical_agreement audit dispatch returning None for non-jsonl-canonical.
- `libs/engine/src/engine/preflight.py:381-394` — _arrival_preflight agreement audit docstring stating it is a later cut.

Not covered: None. Every cited location and caller in the workspace was inspected directly.

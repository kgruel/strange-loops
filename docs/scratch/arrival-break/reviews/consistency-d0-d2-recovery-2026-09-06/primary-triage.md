# D0/D2 focused recovery review — primary triage

Fable-low returned **REVISE**, one blocker, on packet
`4e83e937df0897cd03bc4b97b2d68b9ac0a315bcea721706ad0abfbc89e77a59`.
The first two executable counterexamples were confirmed fixed. The remaining
fresh-token completed-slot bypass is accepted as a correctness finding.

A completed slot's original pending/index/completion evidence must be checked
independently of the token in the new invocation. Selecting a new request token
does not remove the old slot's evidence. The same substituted-slot fixture must
refuse under original-token creation, original-token recovery, and fresh-token
creation, including when the original token index is absent.

The correction is limited to that completed-slot validation path and regression
coverage. The next focused review will inspect it against the retained source.

Optional notes are not blockers: the local custody root is not an authenticated
external key-history witness; created-provenance completion records do not
independently pin public material against simultaneous replacement of binding
and key files. Arrival writes independently validate current signing material
against captured lineage history. Treat stronger local receipt integrity as a
separate hardening decision. Conservative incomplete classification for malformed
JSON remains honest. Index repair before a later candidate refusal is documented
as an explicit partial metadata repair, not a zero-effect read.

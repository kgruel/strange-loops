# D0/D2 directory durability review — primary triage

**REVISE**, accepting Fable-low’s one blocker on packet
`376ad9ba3720935261fe603908001efab0fbae99810687445b1a2c97558ced12`.

The imported-key recovery branch with both private/public files visible reloads
and validates the key but skips its directory fsync. If import linked the public
file and the following sync failed, explicit recovery could publish the binding
without making that prior link durable. Root checked this asymmetric branch;
creation and completed-binding paths already repeat the sync. The correction
must sync after complete pair and expected-public validation, including recovery
without the original import source. Add an injected public-link/sync interruption
regression, run the full isolated custody suite, and request focused follow-up.

Fable confirmed the directory ordering, nested ancestor retry, read-only
resolution, provider-owned symlink refusal, and completed-binding retry fixes.
Its optional notes are not blockers: centralizing existing-directory syncing,
reducing repeated ancestor fsync work, and direct root-mkdir interruption coverage.
The tests observe sync ordering; no physical power-loss test is claimed.

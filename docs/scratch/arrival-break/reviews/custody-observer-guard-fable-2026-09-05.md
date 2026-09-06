# Custody observer input correction

Status: locally validated; Fable review queued until the 21:20 CDT session
reset. No external verdict is claimed.

Root's initializer audit found that key creation joined an observer as a raw
filesystem path. Absolute paths and parent/dot/empty components could select
another directory or alias the flat self-observer key. The load-side guard
covered only empty names and parent components.

One shared guard now covers creation, observer-directory lookup and the
domain-specific load helpers. Normal slash namespaces remain supported;
creation/path lookup refuse malformed names and load helpers return no signer.

Seven new creation tests failed before the fix; afterward all 27 custody tests
passed, including a load-side regression using an existing flat key. Scoped
Ruff passed. Test paths and key material were temporary.

Queued full-source packet:
`/tmp/loops-arrival-review/custody-observer-guard-fable-prompt.txt`.

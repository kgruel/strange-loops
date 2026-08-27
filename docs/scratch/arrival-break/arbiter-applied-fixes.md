# Arbiter-applied fixes — arrival-break arc

Pipeline rule: arbiter-applied fixes have no independent gate; sol is their only
independent verification. Every entry here MUST appear at the top of the next sol
brief's unverified-fixes table. Remove entries only when a sol round has PASSed them.

| commit | finding | fix | arbiter verification |
|---|---|---|---|
| 8aa4c619 | `finding:engine-tests-masked-sign-dependency` — PR #9 first per-package CI exposure: engine conftest imports sign.ed25519, masked by local workspace env | `sign` added to engine `dependency-groups.dev` + `tool.uv.sources`; runtime injection boundary untouched | Mutation-verified in minimal `UV_PROJECT_ENVIRONMENT` closure: reverted → CI's exact ModuleNotFoundError; applied → 1913+1skip green |

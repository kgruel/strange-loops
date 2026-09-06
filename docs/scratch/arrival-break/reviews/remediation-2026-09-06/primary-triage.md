# Primary remediation review judgment

The six reproduced behaviors from the prior Fable follow-up are remediated.
See `../../remediation-2026-09-06.md` for implementation decisions and remaining
architectural scope. Three Fable 5.1 static reviews ran at low effort, sequentially;
all finished. Final source hashes match the latest packet covering each file.
No substantive reviewer other than Fable was substituted; CLI helper usage is
retained separately in the raw modelUsage records. No reviewer jobs remain.

## Review outcomes

1. **Runtime/query/results:** Fable found that a second output-close error could
   mask a source error. Root reproduced both ArrivalError and PermissionError
   cases, fixed cleanup to preserve the primary exception plus a note, and added
   regressions. Its empty-origin ownership question became a failing hydration
   test for an empty-named candidate; the owner check now requires a nonempty
   name. Literal prefixes and recovery result semantics had no further findings.
2. **Custody and follow-up:** Fable found reserved filename components could
   poison key paths and an optional nested fallback could block a valid flat
   self key when another observer had a case-variant name. Both were fixed with
   regressions. The related non-directory error and portable case-branch coverage
   concerns were addressed too. Root retained refusal for an exact self symlink
   instead of allowing it to cause a new flat key. Export and boundary follow-up
   changes had no further defects in this review.
3. **Custody namespace follow-up:** Fable confirmed the listed fixes and raised
   a filename-normalizing filesystem limitation. Primary accepts **refusal** as
   the intended consequence of this layout's exact-spelling policy: if a label
   cannot round-trip through directory names, treating a rewritten spelling as
   the same observer would merge identities without persisted identity evidence.
   This is not a promise that all Unicode labels work on every filesystem.
   Supporting those labels there requires an encoded path or explicit identity
   mapping, a separate custody-layout portability change. No identity-normalizing
   workaround or silent fallback was applied.

The last review's other questions do not establish a remaining silent failure:

- A dangling differently spelled symlink can raise FileExistsError during mkdir;
  no key is minted. Consistent error wording across malformed filesystem states
  is optional diagnostic cleanup, not unsigned fallback or successful custody.
- A preexisting poisoned reserved path containing a directory instead of a key
  fails loudly. This pass prevents new poisoning and never removes prior evidence
  or automatically migrates existing keys.
- `ed25519` without a suffix does not collide with either reserved filename and
  remains a valid directory-mapped observer component.

## Integration evidence

| Suite | Result |
| --- | --- |
| Engine | 2,510 passed, 1 skipped |
| SDK | 494 passed |
| Sign | 40 passed |
| Custody | 50 passed |
| Architecture | 101 passed |
| Minimal CLI including wheel smoke | 8 passed |
| Migrate | 69 passed |
| Legacy CLI tick/fact signing composition (Terra) | 32 passed |

Root ran all suites except the separately attributed legacy CLI subset. The
engine/sign code was unchanged by the final custody namespace refinement; SDK
and custody were rerun afterwards. Owning-package scoped Ruff and diff checks
pass. Legacy vertex.py UP017/SIM108 debt remains outside this change. A combined
root Ruff invocation classifies custody imports differently from its owning
package; the owning-package configuration is the recorded validation.

Raw packets/results are in this directory and its two named subdirectories.
`scope-check.json` verifies every packet and the final source hashes, recording
which later packet superseded an earlier revision. `validation.json` records
counts and the failing/passing regression evidence.

No production commits, staging, push, live-store migration or key edits occurred.
The worktree remains `arrival/finish`; main checkout remains clean.

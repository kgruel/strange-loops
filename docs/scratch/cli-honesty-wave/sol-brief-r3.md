# Cross-family review brief — cli-honesty-wave, round 3

Round 2: five of six r1 fixes PASS across your evasion variants; one FAIL
(R2-F1). That fix has now landed. This round: verify it, sweep for anything
it disturbed, and re-call convergence.

## 1. Anchor
- Repo: /Users/kaygee/Code/loops — branch `cli-honesty-wave`
- Full-wave diff: `git diff 17783fd...HEAD`
- This round's primary target: commit `a52017d` (+ merge b7888f8b) — the
  ONLY code change since your r2 review. Everything else you have already
  verified; do not re-litigate PASSed dispositions without new evidence.
- Receipts: sol-r2-stdout.log, r1-remediation-report.md (R2-F1 addendum)

## 2. R2-F1 fix under review, with its ratified ruling
`resolve.parse_ref_token` extracted from the resolver's ref-field acceptance
(non-empty, no whitespace, Address.parse WITH a kind); the resolver loop and
the cite gate both call it — one spelling of the discriminator. Ratified
consequence: `ref=barekey` ALONE now refuses (arbiter ruling: the meaningful
line is late-bindability — an inert valid address can light up when its kind
is declared; a bare key never can). Malformed tokens beside a storing cite
WARN and stay raw in the payload; storage itself unchanged.

## 3. Verify empirically
- Your r2 reproductions verbatim: `ref=:x`, `ref=kind:`, quoted prose —
  refuse exit 2, nothing stored, dry-run and --json included.
- Evasion variants of the NEW discriminator: whitespace-embedded tokens,
  unicode lookalike separators, `kind:` with trailing comma shapes,
  slash-form legacy refs (must still work — parity tests pin them),
  bare-key-plus-inert mixes, empty ref= combined with -m.
- Regression: all-inert stores; partial-resolve stores with WARN; the
  parity family (verb-first / vertex-first / raw emit) refuses identically.
- Full suite + ./dev check; suite baseline 2509 passed / 1 xfailed.
- CLI via `uv run --package loops loops ...` only.

## 4. Verdict format
R2-F1: PASS/FAIL with evidence. New findings `[R3-F<n>]`. Overall:
CONVERGED / NOT CONVERGED with rationale.

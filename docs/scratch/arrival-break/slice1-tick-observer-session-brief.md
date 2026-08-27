# Slice-1 gate: envelope `observer` design session — brief

Open sub-ruling from `decision:design/arrival-wire-v1-seam-triage`: the tick record's
envelope `observer` re-spelling ("a name is not an authorship claim" — ruled; the
replacement spelling is open). Wire v1 pins only after this session. Migration re-makes
every outer signature, and zero `.arrival` stores exist — every option below is
currently free; after first adoption none of them are.

## What the field does today, per record kind

| kind | envelope `observer` value | outer sig covers it? | source |
|---|---|---|---|
| genesis | custodian identity passed at mint — genesis is "its custodian's act" | yes (genesis must be signed) | `arrival.py:813,822`, `arrival_store.py:131-134` |
| fact | echo of `body.observer` (row col 3) | yes when signed | `arrival_store.py:462` |
| batch | **first row's** observer (`rows[0][3]`) — privileges row 0 when a batch spans observers | yes when signed | `arrival_store.py:526` |
| tick | the tick's NAME (row col 1) — the ruled-out seam | **no — ticks pass `signer=None`**; the envelope observer on a tick is an unsigned label today | `arrival_store.py:462,465` |
| key | the INTRODUCING record's observer (body names the observer the key speaks for) | yes (must be signed by an already-valid key) | `arrival.py:434,493-495` |

Grammar today: `observer` must be a non-empty string for every kind (`arrival.py:390-391`).
The outer content commitment is `(k, at, observer, origin, body)` (`arrival.py:550`).
Inner signatures are unaffected by any option here (fact domain covers row fields only;
a tick's inner sig covers its 10 row fields, name included — tick authorship is already
committed *inside* body regardless of the envelope).

## The widened seam (found in plan-session exploration)

For facts, `observer` duplicates `body.observer`, and `body` is already inside the outer
commitment — so the envelope field adds no commitment coverage for facts either. The
session should rule what the field is FOR across all kinds, not just patch ticks:

- If it is an **authorship echo** → ticks have none to echo (hence the seam), and batch's
  row-0 privileging is a second wart of the same reading.
- If it is a **custody claim** (who produced the record) → genesis already uses it this
  way, and facts/batches carrying the *author* there is the inconsistency.

## Candidates

**A. Custodian identity for ticks (and possibly batches).** Uniform non-empty grammar;
true claim ("the custodian's fold engine produced this record"); consistent with genesis.
Follow-on to pin in the same ruling: WHICH label (the vertex's own observer, e.g.
`project`? the signing identity?). Tension: ticks are outer-unsigned, so it's an
unverifiable claim unless ticks also gain outer signatures (scope step — not currently
ruled).

**B. Empty observer for ticks.** Claims exactly nothing — coherent with ticks being
outer-unsigned. Cost: kind-conditional grammar (non-empty except tick) or a global relax
of the non-empty rule. Precedent: `origin` may already be empty.

**C. Re-derive: observer = custody-producer label for ALL kinds.** Facts/batches change
too (envelope observer becomes the custodian, authorship stays in body where it already
lives and is committed). One consistent meaning; kills the batch row-0 wart. Largest
change, still free pre-adoption; fixture regen identical in kind to A/B.

**D. Drop `observer` from the envelope.** Authorship in body, custody in `sig`; the
outer commitment becomes `(k, at, origin, body)`. Maximal dissolution; changes the
commitment shape (legal pre-adoption, migration re-signs). Cost: the envelope loses its
human-scannable "who" column — relevant to the git-diff-readability goal of the future
git-hosted backend profile.

## What pinning requires (any option)

Grammar rule in `validate_record` + codec + conformance-vector regen + wire-format.html
envelope table update + sub-ruling appended to `decision:design/arrival-wire-v1-seam-triage`.
A and B are tick-local; C and D also touch fact/batch/genesis mint sites and the
commitment helper (`content_commitment`, `arrival.py:537-551` — D only).

## Also on the agenda (same session, cheap while the file is open)

- Batch `rows[0][3]` privileging (`arrival_store.py:526`) — inherit the main ruling.
- Should ticks gain outer signatures? Not ruled anywhere; A implicitly raises it. If
  deferred, say so explicitly so wire v1 pins with ticks outer-unsigned on purpose.

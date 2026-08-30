# Slice 4 WP2 — fix round 1 (gate BLOCK + reviewer blockings, arbiter-ruled)

## Working directory — verify FIRST

    /Users/kaygee/Code/loops-wt/s4-wp2

Prefix EVERY command with `cd /Users/kaygee/Code/loops-wt/s4-wp2 && `. First action:

    cd /Users/kaygee/Code/loops-wt/s4-wp2 && pwd && git branch --show-current && git log --oneline -1

Expected: branch `slice4/wp2`, HEAD 5f5149d9. Otherwise STOP and report. Test env:
`TMPDIR=/Users/kaygee/Code/loops-wt/s4-wp2/.tmp`, pytest `--basetemp=.../.tmp/pt` — EXCEPT
any run of the ENGINE suite, which must use `TMPDIR=/private/tmp/s4wp2-tmp` (create it):
one engine test asserts the state root is not under $HOME.

## EXECUTE YOURSELF — DO NOT DELEGATE

No one else exists to do this. Deliver everything in one response.

## Context

You are fixing findings from the independent gate + adversarial review of WP2 (commits
c966d981, 536f737f, 5f5149d9 in this worktree). You have no prior context — this brief is
complete. Every fix is RULED. If a prescription seems wrong against the code, STOP on that
item and report; never substitute your own design.

## Scope fence

You MAY edit ONLY `libs/migrate/**`. Nothing else — no engine/store/lang/apps/docs/rule
edits, no reformatting outside your changes, never touch `.loops/` or anything outside the
worktree, never run `sl`/`loops` emit. The quarantine ratchet and Rule 4 row must stay
green/true (your changes must not add cross-lib imports). STOP and report anything that
seems to need an out-of-fence change.

## The fixes

**F1 — LegacySource consolidation (root cause of TWO blockings; ruled).** The gate measured
72% of transform.py's batch block as verbatim inventory.py — the batch-envelope grammar now
exists three times, because the JSONL transform branch re-opens and re-parses the file
instead of consuming a reader, and the sqlite branch consumes a reader that validates
nothing. Consolidate to the ratified architecture: ONE validated row-stream layer
(`src/migrate/legacy_source.py`) that BOTH arms produce and BOTH consumers share:

- It yields, in ruled source order, classified units: a validated flat fact row, a validated
  single-observer batch group (intact, with intra-group order), a validated tick — plus,
  accumulated across the WHOLE source, the refusal classes (codec-invalid / mixed-observer /
  absent-or-empty-observer, see F2).
- `inventory()` becomes an aggregation over this stream (counts, censuses, hashes stay as
  they are today). The transformer consumes the SAME stream and contains ZERO grammar
  re-implementation — delete the duplicated batch-envelope logic from transform.py.
- The sqlite arm's stream applies the SAME semantic validation before yielding (observer
  must be a non-empty string; ts numeric; payload/field shapes per the frozen grammar —
  probed failures today: ts-as-TEXT and NULL-ish values reach body_of_fact_row and
  ArrivalBodyError escapes transform() raw). After this, NO ArrivalBodyError, JsonlCodecError,
  KeyError, or TypeError can escape the public inventory()/transform() surfaces for any
  malformed source — everything lands in the migrate-family refusal with line/rowid
  coordinates. Mirror all three seam-defense tests onto the sqlite arm.

**F2 — Empty-observer cohort (arbiter ruling on the reviewer's B1; REAL data: 147/190 rows
in one live experiment store carry observer='').** The legacy schema permits '' (`TEXT NOT
NULL`); engine refuses it (arrival.py:483-484). Ruling: `''` joins the absent class — the
claim is "no author recorded", a location claim; '' is neither declared nor undeclared and
gets no slot of its own. Concretely: (a) the absent-or-empty class in the refusal covers
batch rows AND flat fact rows AND ticks, in BOTH arms, counting '' and missing/None
identically but reporting which spelling occurred; (b) the refusal fires at inventory (before
any target bytes — same posture as GF-3) and enumerates every offending line/rowid with a
per-observer-spelling census; (c) the §G.3 exception-report census guards
(`if fr.observer:` at transform.py:243,328) are REMOVED — the cohort must be visible, not
skipped; (d) NO re-attribution, NO custodian-adoption of authorless rows — that ceremony is
deliberately unbuilt (slice-6 decision with evidence in hand); advisory prose in the message
may say the store needs an out-of-band ruling before it can migrate.

**F3 — Dropping-rule regroup (arbiter ruling on B3, both seats).** `Transform.map_fact`
returning None currently re-decides record kind (partial drop: batch → fact) or silently
vanishes a line (full drop, no report entry). Engine's own `body_of_batch` docstring made
the opposite call ("a collapse would be this module deciding a record's kind behind it").
Ruling: (a) a rule that drops SOME rows of a batch group → typed migrate-family refusal —
the sidecar cannot re-decide a ceremony's composition (the same principle as GF-3
refuse-not-split); (b) a rule that drops a WHOLE unit (flat fact, entire batch group, tick)
is legal ONLY as a named exception-report entry carrying the source coordinate and the
rule name (§I.1's "any dropped or out-of-scope row" line anticipates exactly this) — silent
vanishing dies; (c) kind re-deciding code is deleted. Tests for all three.

**F4 — signer is REQUIRED (gate B1).** `signer=None` is the default and produces unsigned
key introductions that engine structurally refuses ("a key introduction carries no
signature") — mid-migration, after genesis. Construction over detection: make the state
inexpressible — the signer is a required parameter of the transform run (no default). A
declaration whose observers carry keys cannot even be attempted unsigned. Update callers
and tests.

**F5 — Declared-key shape validation (gate non-blocking, ruled in).** A malformed declared
key currently produces a draft that only engine's append refuses. Validate every declared
observer key's shape at transform setup (engine exposes the shape check the grammar uses —
find it in engine/arrival.py, e.g. the `_key_shape_fault` logic reachable via public
surface; if only private, replicate the CHECK CALL not the logic — STOP and report if
neither is cleanly reachable) and refuse with a migrate-family refusal naming the observer
(location claim: "declaration carries a key of the wrong shape for <observer>").

**F6 — Residue + typing sweep.** (a) Six dead imports left by P1-P3 in inventory.py and
transform.py — remove. (b) transform.py:187-204: the declaration parameter's Path|str|
VertexFile union is mishandled (Pyright: .name on str, .observers on Path/str) — narrow the
public surface to ONE input type (VertexFile), with a small explicit helper for path/str
parsing at the call boundary. (c) Remove the format-detection suffix clause
(`or suffix in (".sqlite",".db")`) — the magic header already decides; the suffix arm can
only misroute. (d) Document the sqlite arm's facts-then-ticks ruled order in the
LegacySource docstring. (e) The missing-self-observer declaration error becomes a typed
migrate-family refusal, not a bare ValueError.

**F7 — Test-strength gaps (reviewer non-blockings, ruled in).** (a) An intra-batch row-order
test: reversing the rows of a batch group must fail a test (seq 0..N-1 must follow source
order). (b) Add a SIGNED batch row to the fixture corpus so ruling 3 (inner signatures
byte-for-byte) is exercised on the batch path.

## Acceptance bar

COMMIT FIRST (one commit per F-item or sensible grouping), THEN break/restore proofs — paste
failing output, restore, paste green, paste the empty production diff after each:

1. F1: re-introduce a direct file re-parse in the transformer's jsonl path bypassing
   LegacySource → a seam test fails. Also: feed a ts-as-TEXT sqlite row → typed refusal,
   never ArrivalBodyError (paste before/after behavior).
2. F2: a sqlite fixture with observer='' rows → inventory refuses, enumerating rowids with
   the '' spelling distinct; remove the refusal → test red.
3. F3: restore the batch→fact collapse → the regroup-refusal test fails; restore silent
   full-drop → the exception-report test fails.
4. F4: pass no signer → TypeError at the call site (required param), and no code path
   constructs an unsigned introduction (grep + test).
5. F7a: reverse intra-batch order in the transformer → the order test fails.

Final checks, paste output: `uv run pytest libs/migrate tests/architecture -q` all green;
`git status --short` clean but `.tmp/`; quarantine grep empty; `grep -rn "def transform" `
usage shows one grammar implementation (state where the batch grammar now lives and that
inventory.py/transform.py contain no copy).

## Report format (stdout, one shot)

1. Per F-item, what changed file by file. 2. Evidence per proof. 3. Anything you stopped on
(F5's reachability question especially). 4. Found-but-left-alone. 5. Honest unverified list.

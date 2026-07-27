# Track B implementer report (Opus 5 agent, 2026-07-27)

Verbatim final report from the implementing agent. Claims herein are the
review's TARGET, not its authority — verify, don't trust.

---

TRACK B FINAL REPORT

=== COMMITS ===

loops (feat/010-surfacing, NOT pushed):
  799c0a3  docs(010-wave): loops-go protocol queue — one coordination ledger
  d296e08  refactor(protocol): relocate the loops-go conformance generators into the workspace
  92451e0  feat(protocol): family-3 vector generator — same-ts id tie-break

loops-go (feat/track-b-batch off 94f7987, NOT pushed):
  bcb2308  tools: generation moves to the loops repo; sweep the path residue
  76c8378  conform: same-ts id tie-break vector (§4.6 / §6.2) — vector family 3

Both trees clean. Branch r2-replay-conformance untouched at 94f7987.

=== (1) GATE OUTPUTS ===

loops — ./dev check (uv run pytest tests/ -q):
  46 passed in 1.77s
  Baseline before any change was also 46 passed. No ratchet weakened, no
  allowlist grown, no baseline touched. tools/ sits outside every derivation the
  arch suite walks: LIBS from libs/, APPS + Rule 12 _source_roots from apps/*/src,
  Rule 3 containment (_misplaced_app_python) from apps/. Same shape as the
  existing top-level benchmarks/ directory.

loops — ruff on tools/:  38 errors, ALL E701 (multiple-statements-on-one-line-colon).
  That is the `if op == "count":   return Count(...)` dispatch style carried
  verbatim from the originals; benchmarks/ has a comparable nit (1 x E401) and
  nothing in the repo runs ruff over either directory (ruff config is per-package
  under libs/*/apps/*; root ./dev check is pytest only). Left as-is so the
  relocation diff reads as a move.

loops — generator smoke, all four from committed state:
  gen_vectors OK / gen_store_fixture OK / gen_merge_fixture OK / gen_tie_fixture OK
  Running one with no destination refuses (SystemExit) rather than guessing.

loops-go:
  gofmt -l .      -> (no output, clean)
  go vet ./...    -> clean
  go test ./...   -> ok  github.com/kaygee/loops-go/internal/conform  0.404s
                     (atoms and store: no test files)

loops-go per-test, `go test ./internal/conform/ -v`:
  --- PASS: TestFoldVectors                    (30 fold vectors @ python 581df73)
  --- PASS: TestParseVectors                   (28 scenarios, 35 cases)
  --- PASS: TestOrderSensitivityProperty
  --- PASS: TestApplyPurity
  --- PASS: TestDeterminism
  --- PASS: TestM1StoreReplayParity
  --- PASS: TestMergeCommutativity             (2 subtests: merge_ab.db, merge_ba.db)
  --- PASS: TestSameTSIDTieBreak               <-- THE FAMILY-3 TEST, PASSING
      --- PASS: TestSameTSIDTieBreak/entities
      --- PASS: TestSameTSIDTieBreak/log
      --- PASS: TestSameTSIDTieBreak/tags
  --- SKIP: TestSameTSIDTieBreakTopNEviction   <-- the §4.6 facet; see (5) Q6

  8 top-level PASS, 1 SKIP, 0 FAIL. Was 7 top-level before this batch.

=== (2) ARTIFACT-CLASS JUDGMENT ===

CHOSE: store fixture (testdata/stores/tie.{db,expected.json}) + a new Go test
walking it. NOT a fold vector.

Rationale, verified against how the Go harness actually consumes each class:
  - Fold-vector class: schema is {name, folds, initial, payloads, expected,
    order_sensitive}. vectors_test.go:78-80 applies payloads in ARRAY order. So
    ordering is an INPUT to that class and can never be the thing under test.
    No ids, no store, no time axis anywhere in the schema.
  - Store-fixture class: a .db carries ids, and store.ReadFacts's
    `ORDER BY ts, id` (store/sqlite.go:41) is literally the code the tie-break
    lives in. Only this class can exercise it.
  - SPEC §6.2 already said so in its own closing parenthetical ("adding it to
    the id-less fold vectors would have no replay-order step to exercise"). I
    updated that parenthetical to point at the fixture that now exists.

Wired as its own file internal/conform/tie_test.go rather than folded into
store_test.go, because M1's proc.db is deliberately axis-blind (its ts and id
both ascend with insertion, so witness and event order coincide) and the two
fixtures are asserting opposite things.

=== (3) HOW THE TIE IS CONSTRUCTED, AND THE FAILURE PROOF ===

Five facts. Column 1 is insertion order (= rowid); the id letter fixes (ts, id)
order and runs backwards relative to it.

  rowid  id     ts       pid  score  tag   -> (ts,id) replay position
    1    TIEE  1000.0     z     50   z2            5
    2    TIEC  1000.0     x     50   x             4
    3    TIEB  1000.0     y     50   y             3
    4    TIEA  1000.0     z     50   z             2
    5    TIED   999.0     w     10   w             1

  rowid order : TIEE TIEC TIEB TIEA TIED
  event order : TIED TIEA TIEB TIEC TIEE

Ids are 26-char (TIE + one ordering letter + 22 digits), so a single letter is
the whole tie-break signal. Four of five share one ts. The fifth (TIED/w) sits
at a LOWER ts with the HIGHEST id and the LAST rowid — that pins ts as primary
and id as tie-break rather than sort key, so an id-only sort also fails.

Four folds read that order, each failing differently under a wrong one:
  - TopN(target=top, key=pid, by=score, n=2, desc): three keys tied at score 50.
    THE §4.6 case.
  - Upsert(key=pid): pid z is written twice at the SAME ts — last-write-wins is
    decided purely by id.
  - Collect + Window(size=3): order-sensitive by construction, so a wrong order
    shows up as a sequence, not just a set.

Both answers ship in the fixture: `expected` ((ts,id) replay) and
`expected_rowid_order` (rowid replay). TestSameTSIDTieBreak asserts a MATCH
against the first AND a MISMATCH against the second. Without that negative
control the vector could silently decay into a tautology if regenerated from an
order-blind table.

VERIFIED THE TRAP SPRINGS — not asserted, executed. I temporarily patched
store/sqlite.go `ORDER BY ts, id` -> `ORDER BY rowid` and re-ran:

  --- FAIL: TestSameTSIDTieBreak/entities
        got  z -> {note:"first", tag:"z"}
        want z -> {note:"later", tag:"z2"}
  --- FAIL: TestSameTSIDTieBreak/log
        got  [z2, x, y, z, w]
        want [w, z, y, x, z2]
  --- FAIL: TestSameTSIDTieBreak/tags
        got  ["y","z","w"]
        want ["y","x","z2"]

All three facets red. Reverted and re-verified (grep -c 'ORDER BY ts, id' -> 2).

Unstable sort: with three items tied on BOTH by and ts, an unstable sort can
retain any 2-subset, so it cannot reliably produce `expected`. The generator
asserts the §4.6 outcome explicitly (set(expected["top"]) == {"z","y"} vs
set(expected_rowid_order["top"]) == {"z","x"}), so a fixture edit that keeps the
two states distinct but stops exercising the TopN tie fails at generation time
rather than silently weakening the vector.

=== (4) PYTHON-SIDE AGREEMENT ===

`expected` is not hand-written. It is engine + atoms output:

  1. Facts are appended through engine.sqlite_store.SqliteStore with
     id_override, i.e. the real write path.
  2. The generator reads them back through the PRODUCTION replay path,
     SqliteStore.since_raw(0) (sqlite_store.py:907-931, "SELECT kind, ts,
     payload FROM facts WHERE rowid > ? ORDER BY ts, id", with _ts injected).
  3. It ASSERTS since_raw's output == the independently-computed (ts,id) sort of
     the fixture table. So if the reference implementation's replay order ever
     changed, generation fails rather than pinning a stale order.
  4. `expected = spec.replay(by_event)` — real atoms Spec.replay over those
     payloads. `expected_rowid_order = spec.replay(by_rowid)`.
  5. Three further generation-time assertions: by_rowid != by_event (the fixture
     discriminates), expected != expected_rowid_order (the trap springs), and
     expected["entities"]["z"]["tag"] == "z2" (the same-ts Upsert LWW landed the
     later id).

So Python's replay path and the Go reader are both asserted against the same
pinned order, from opposite sides.

=== (5) JUDGMENT CALLS / WHAT RESISTED ===

A. THE BIG ONE — Q6: Go CANNOT satisfy §4.6, and it is a protocol gap, not a bug.
   This is what resisted. atoms/fold.go knowingly tie-breaks TopN by KEY STRING
   (its own comment says "This DIVERGES from Python for equal `by` values (none
   in the conformance corpus)"; FINDINGS §3 logs it as a "concrete fix-both").
   So a fully-discriminating tie vector turns the suite red.

   I traced whether the fix was actually available. It is not. FINDINGS §3
   offers "preserve (ts, id) insertion order in the target map (or re-derive
   it)" — there is no re-derivation. Arrival order is recoverable from neither
   side of what a fold sees: the target is an unordered map[string]any, and the
   payload carries _ts but NO id (ReadFacts injects the first, drops the
   second). For items tied on BOTH `by` and `ts` — exactly this fixture — no
   content-derived rule can order them. I also checked the "evict the newcomer"
   heuristic: it is correct when the newcomer is in the tied-minimum group but
   wrong when ties exist among incumbents (N=2, {a:50,b:50}, insert c:60 —
   Python evicts b, the later incumbent, and Go cannot know which that is).

   Closing it needs a protocol decision, not a patch: carry the id into the fold
   layer, or make a TopN target an ordered map — which JSON's value model says
   objects are not, and which SemanticEqual currently compares
   order-insensitively.

   MY CALL: ship the STRONGER fixture rather than one weakened to match the
   implementation. I could have aligned key-string order with arrival order,
   which would have made Go pass fully while still catching rowid replay — the
   brief's literal failure modes. I rejected that as designing the test to the
   implementation. Instead the §4.6 facet is split into
   TestSameTSIDTieBreakTopNEviction, which (a) still asserts Go is not
   rowid-replaying, and (b) RETIRES ITSELF: if Go ever agrees with Python there,
   it FAILS with "the gap closed: promote the facet into TestSameTSIDTieBreak,
   delete this test, retire FINDINGS §3". A muted test that cannot notice its
   own premise expiring is exactly what FINDINGS I1 complains about.

   Recorded as Q6 in the ledger, and in FINDINGS §3 + §4.6's parenthetical.
   IF YOU DISAGREE with the skip, the alternative is the weakened fixture; say
   so and I will swap it.

B. docs/dev/ IS GITIGNORED. The brief's specified path sits under a directory
   the repo ignores as "Personal dev notes" — docs/dev/lifecycle-spec-delta-090.md
   is itself untracked and already cited from tracked docs, a latent dangling
   pointer. Since loops-go's README, FINDINGS and SPEC now cite the ledger BY
   PATH, leaving it untracked makes every one of those dangle for anyone else who
   clones. I kept the brief's path and unignored the single file using the
   negation idiom the .gitignore already uses (docs/dev/* + !the-file), so
   docs/dev/ stays personal otherwise. Worth your call whether to promote it to
   tracked docs/ instead — docs/scratch/ IS tracked, docs/dev/ is not.

C. SPEC.md EDITS. I updated §4.6's and §6.2's status parentheticals (both said
   the tie vector "should be added" / "still awaits") and the conformance
   appendix. NO normative text changed. Reason: leaving "a tie vector should be
   added once §6.2 is frozen" in the spec after adding it is precisely the
   residue-sweep failure to avoid. Flagging because the 090 wave carried a
   standing "S5 does not edit loops-go/SPEC.md" ruling — that was scoped to a
   spec-delta and these are status facts, but revert is cheap if you want the
   spec untouched by this batch.

D. PARITY EVIDENCE, and a finding it produced. Regenerated all three existing
   artifacts into a scratch checkout:
     - fold_vectors.json, parse_vectors.json, proc.expected.json,
       merge.expected.json: differ in EXACTLY TWO KEYS, python_commit and
       generated_by. Every vector, fold, state_field and expected state
       unchanged.
     - proc.db / merge_ab.db / merge_ba.db: NOT byte-identical, but the facts
       tables are IDENTICAL ROW-FOR-ROW (rowid, id, kind, ts, observer, origin,
       payload) at 5/4/4 rows.
   The byte diff is NOT relocation noise. I traced it into sqlite_master: the
   committed .db files predate the attestation columns (facts.signature;
   ticks.prev_hash / window_start / fact_cursor / window_hash / signature), so
   today's engine writes a wider schema. Harmless to the Go reader, which selects
   columns explicitly. Per the brief I did NOT commit regenerated fixtures — what
   the fixtures should pin is a decision, not a side effect of moving generators.
   Recorded in the ledger's "Adjacent" section; it is the same hole one layer
   down from FINDINGS I3's wanted python_commit == loops HEAD pin-guard.

E. NOT SWEPT, deliberately: the "generated_by" strings inside the
   already-committed testdata/**.json. Those record where those bytes actually
   came from; rewriting a provenance field without regenerating the artifact
   would be a false claim. The next regeneration updates them to "loops:tools/…"
   on its own. Called out in loops-go/tools/README.md so it does not read as
   missed residue.

F. LEDGER CONTENT BEYOND THE BRIEF'S LIST. Two additions, both new information
   this batch produced rather than restatements of the grounding: Q6 (above) and
   the fixture-schema drift (D). Everything the brief asked for is there:
   5 queue members with status/blocking/links, the 5-family table with
   per-family blockers INCLUDING the unnamed witness-exposing-reader
   prerequisite for families 1/2/4/5 and §10's absence for family 5, the four
   settled verdicts (JCS gate SATISFIED, FIVE not eight, the oracle/vector
   five-vs-five name collision plus the oracle count itself being wrong,
   ceremony-refutation at tasked.db rowids 356-360), Q1-Q3+Q5 recorded AS
   QUESTIONS at the design gate, and Q4 recorded as settled by deliverable 2.

=== (6) NOT DONE, per brief ===

No store emissions from the implementer. No pushes. GRP / durable-group-id /
lifecycle / tombstone untouched.

=== FILES (absolute) ===

loops:
  /Users/kaygee/Code/loops/docs/dev/loops-go-protocol-queue.md
  /Users/kaygee/Code/loops/tools/README.md
  /Users/kaygee/Code/loops/tools/_conformance.py
  /Users/kaygee/Code/loops/tools/gen_vectors.py
  /Users/kaygee/Code/loops/tools/gen_store_fixture.py
  /Users/kaygee/Code/loops/tools/gen_merge_fixture.py
  /Users/kaygee/Code/loops/tools/gen_tie_fixture.py
  /Users/kaygee/Code/loops/.gitignore                        (per-file negation)

loops-go:
  /Users/kaygee/Code/loops-go/internal/conform/tie_test.go
  /Users/kaygee/Code/loops-go/testdata/stores/tie.db
  /Users/kaygee/Code/loops-go/testdata/stores/tie.expected.json
  /Users/kaygee/Code/loops-go/tools/README.md                (pointer; 3 originals removed)
  /Users/kaygee/Code/loops-go/{README.md,FINDINGS.md,SPEC.md,atoms/decode.go}
  /Users/kaygee/Code/loops-go/internal/conform/{vectors,store,merge}_test.go

# WP-1 sol re-verdict r3 — SOL-WP1-02 closure only

Branch slice/D-wp1, new tip 12ae9042 (one commit past your r2 review).

Your SOL-WP1-02: _verify_coordinate_schema accepted a standalone
CREATE UNIQUE INDEX (origin 'c') as satisfying D0's table-level UNIQUE.

ARBITER-APPLIED FIX (12ae9042 — you are its only independent verification):
the index-acceptance loop now requires idx_row[3] == "u" (auto-index from a
table-level UNIQUE); the sqlite_schema CREATE-sql regex fallback is unchanged
(that text IS in-table custody). New test
test_standalone_unique_index_does_not_satisfy_table_custody pins the origin-'c'
refusal. Arbiter mutation proof: reverting the origin check fails the test;
restore => 31 green. Suites: engine 1841+1skip, store 157, apps 2525+1xfail.

Question: is SOL-WP1-02 closed as you meant it? Check the diff of 12ae9042 and
answer PASS or FAIL (with what remains). One response. Do not re-review the
rest of the branch.

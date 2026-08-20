QUESTION SET — CAS token production and consumption.

1. libs/engine/src/engine/sqlite_store.py around lines 1411-1438: quote the current code verbatim (the lineage-filtered _decl.*-only CAS predicate). Extend the range as needed to capture the whole function(s) involved — give exact line ranges.
2. Locate EVERY site that produces, parses, or compares the CAS token across the repo — search for the token's field/variable names as used in that sqlite_store.py region (e.g. cas, token, expected head) — file:line, verbatim lines.
3. ceremony.py around line 432: quote the escaped-token persisted-intent-record code verbatim with exact line range; give ceremony.py's full path.
4. Enumerate the token's grammar/format: locate where the token string is constructed (format string, join, f-string) — file:line, verbatim.
5. All tests referencing the CAS token or the intent record — file paths, test names, line numbers.

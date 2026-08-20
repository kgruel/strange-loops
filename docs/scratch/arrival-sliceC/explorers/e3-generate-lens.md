QUESTION SET — generate_lens ordering machinery.

Find the file generate_lens.py (rg --files | grep generate_lens).
1. Its full path, and the line ranges + verbatim code of every place it orders, sorts, or assumes a `ts` (timestamp) field.
2. Every call site of generate_lens (imports and invocations) across the repo — file:line, verbatim.
3. Where declared keys / key declarations live: search libs/ for how a projection or lens declares its key (decl records, Spec fields, KDL lang constructs) — locate the definition sites of any `key` field/attribute on specs, decls, or lens declarations, file:line, verbatim.
4. Any tests covering generate_lens — file paths and the test function names with line numbers.

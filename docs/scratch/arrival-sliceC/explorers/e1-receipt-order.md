QUESTION SET — _receipt_order residue map.

The function `_receipt_order` lives at libs/store/src/store/jsonl.py (around lines 104-126). Locate:
1. The full definition of `_receipt_order` — file, exact line range, verbatim body.
2. EVERY call site, import, or reference to `_receipt_order` anywhere in the repo: libs/, apps/, clients/, dev/, tests (wherever they live), benchmarks/, docs/ (excluding docs/scratch/). Use rg over the whole repo.
3. Any OTHER code implementing the same idea under a different name — sorting/ordering records by receipt, seal, or tick position at read time in libs/store. Search for sort keys involving receipt, seal_seq, tick, position in libs/store/src.
4. Any references in the frozen sidecar last-0.x reader (search for a sidecar/legacy/last-0x reader module and whether it has its own copy of receipt-order logic) — report where that copy lives so it can be fenced OUT of the change.
5. Any docs, docstrings, comments, or config keys mentioning receipt order / receipt-order semantics outside docs/scratch/.

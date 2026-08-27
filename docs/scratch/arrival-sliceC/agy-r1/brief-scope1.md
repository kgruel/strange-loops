SCOPE 1 — the Ordering primitive and its read surfaces (slices C1, C2-part-A, C5).

Files under review (read every changed line; `git diff a49997cd..074a1860 -- <path>`):
- libs/atoms/src/atoms/ordering.py (new) + libs/atoms/src/atoms/__init__.py + libs/atoms/tests/test_ordering.py
- libs/engine/src/engine/store_reader.py (ordered()) + libs/engine/tests/test_store_reader.py (TestOrdered)
- spec/conformance/generate_lens.py + SCHEMA.md + the four new vectors under spec/conformance/vectors/lens/ + libs/engine/tests/test_conformance_lens.py
- libs/engine/tests/test_ordering_checkpoint_dispatch.py

Review categories (proof of work per category):
1. TOTALIZATION SOUNDNESS — is the one sort-key definition correct and genuinely singular? Hunt for any second sort-key spelling anywhere in the cut diff (grep for sorted(/sort(/ORDER BY in changed files). Construct adversarial inputs the unit tests miss.
2. ordered() SEMANTICS — prefix-selects-then-key-orders; probe boundary interactions (prefix window vs exclusion, internal kinds, empty stores, ByKey self-consistency). The fix commit c314a3e7 is in your scope: re-verify its mutation claim yourself.
3. CONFORMANCE VECTORS — are the four new vector families' expected outputs CORRECT (recompute them yourself from the inputs by hand or script, do not trust the generator)? Is the ts family truly byte-frozen (git diff a49997cd..074a1860 -- the two old vector files must be empty)? Could a loops-go reader be broken by the schema change (optional input.ordering)?
4. CHECKPOINT DISPATCH — does the licensing rule (Arrival licenses suffix replay, ByKey cold-folds) have a hole? Try to construct an ordering value or store history where the licensed suffix replay would produce a different fold state than a cold fold WITHOUT any test failing.

# Coupling Kernels Experiment

Tests Gomez-Emilsson's "coupling kernels" claim from
[How to Squeeze Genius Out of LLMs](https://andrsgmezemilsson.substack.com/p/how-to-squeeze-genius-out-of-llms)
as a real mechanism for surfacing latent organization in semantic spaces, not
as a metaphor for persona-prompting.

The bet: scale-sweeping a Mexican-hat (DoG) kernel over an embedded fact set
reveals emergent cluster structure that varies with kernel scale (article's
claim) AND varies with the embedder used (extension — "architecture-via-
vocabulary": different embedders are different vocabularies for organizing
the same content).

## Files

- `perspectives.py` — 6 hand-authored perspectives crossed substance × style;
  toy stress-test for the kernel.
- `toy_minilm.py` — embed toy with `all-MiniLM-L6-v2`, save matrix.
- `toy_gemini.py` — same with `gemini-embedding-001`.
- `sweep.py` — Mexican-hat scale sweep on a saved embedding matrix.
- `real_sweep.py` — full pipeline on `cache/project_decisions.json`
  (296 real decisions from the project store).
- `cache/` — embeddings (gitignored, regenerable from sources).

## Findings so far

### Toy (6 perspectives)

- Kernel mechanism works: clear three-regime structure (isolation → emergent
  K → unity) as σ varies.
- MiniLM and Gemini find _different_ K=3 cluster compositions in their
  transitional bands. The kernel surfaces _whatever_ axis the embedder
  encodes most strongly at medium distance — not necessarily substance.

### Real corpus (296 project decisions)

- Both embedders find rich structure: ~6–9 non-trivial cross-namespace
  clusters plus a single "core" component (~45% of corpus).
- Cleanest cross-namespace finding: ULID identity cluster
  (architecture/ulid-fact-identity, implementation/fact-by-id,
  architecture/ulid-store-schema) — namespace boundary split decisions
  the kernel re-fused.
- Cross-embedder convergence: paradigm/strangeness-collapse cluster
  appears in both — not embedder-specific.
- Embedder-specific: MiniLM finds attention-signal cluster
  (cite/ping-as-attention-signal), Gemini finds search/FTS cluster.

## Next

Instruction-tuned embedder (E5-Mistral) — same content, different
*user-specified* axis, different topology. Tests whether the embedder
itself can be a vocabulary parameter rather than a fixed projection.

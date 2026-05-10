# Coupling Kernels — structure-reveal harness

A composable corpus → embed → kernel → readout pipeline that emerged across
six demonstrators (`real_sweep.py`, `e5_sweep.py`, `antipode.py`,
`bridge.py`, `triage.py`, `temporal.py`).

The original investigation tested Gomez-Emilsson's "coupling kernels" claim
from [How to Squeeze Genius Out of LLMs](https://andrsgmezemilsson.substack.com/p/how-to-squeeze-genius-out-of-llms)
as a real mechanism for surfacing latent organization in embedded fact sets.
Six confirmed hypotheses (kernel-emergent-k, embedder-as-vocabulary,
instruction-as-vocabulary, cross-namespace-clusters, antipode-as-negative-space,
concept-drift-temporal) made it worth standardizing — a new experiment is
now a `Query(...)` value, not a 200-line script.

## Dimensional model

The pipeline has **four axes**, plus a Compare operator:

| Axis | What it specifies |
|---|---|
| **Corpus** | which facts to embed (vertex, kinds, time-window, fold-dedup, min-chars) |
| **Embedder** | how text → vector (model + optional instruction) |
| **Kernel** | how vector-space → graph (DoG with σ + ratio; injectable scale_finder) |
| **Readout** | how graph → finding (`components`, `bridges`, `antipodes`, `lineage`, `triage`) |

`compare(qa, qb, op)` is an operator over `QueryResult`s — `jaccard`,
`lineage_match`, `intersect_components`. Not a fifth axis.

## Schema

```python
from core import Corpus, E5InstructEmbedder, Kernel, Query, Readout, run

q = Query(
    corpus = Corpus(vertex="project", kinds=("decision","thread","task"),
                    min_chars=50),
    embedder = E5InstructEmbedder(instruction="Group by design concern."),
    kernel = Kernel(),                    # default: DoG, sigma=auto-richness
    readouts = (Readout("bridges", {}),),
)
qr = run(q)                               # → QueryResult
```

`QueryResult` carries `rows`, `E`, `D`, `sigma`, `components`, `readout_outputs`.

## Cache

Embedder cache key is **per-item content-hash**, never batch-hash:

1. **Append-only correctness.** Adding one item invalidates only that item's
   cache entry, not the corpus.
2. **Cross-corpus overlap.** Two corpora sharing 80% of items pay only the
   20% delta, regardless of how the corpora were constructed.

Wrap any `Embedder` with `CachedEmbedder(inner, cache_dir)` to enable.

## Layout

```
core/
  corpus.py       Corpus dataclass + sqlite loader
  embedder.py     Embedder ABC, STEmbedder, E5InstructEmbedder,
                  GeminiEmbedder, CachedEmbedder
  kernel.py       cosine_dist, dog_kernel, positive_components,
                  find_richness_scale; Kernel
  query.py        Query, QueryResult, run(), RunContext
  compare.py      jaccard, lineage_match, intersect_components, compare()
readouts/
  components.py   ComponentsParams + cluster listing
  bridges.py      BridgesParams + cross-kind detection
  lineage.py      LineageParams + previous-result match
  antipodes.py    AntipodesParams + mechanical + LLM-synthesized
  triage.py       TriageParams + apparatus_era + cross_reference_density (rg)
runs/
  01_real_sweep.py    MiniLM + Gemini namespace baseline
  02_e5_sweep.py      E5 mechanism vs domain reshuffle
  03_antipode.py      Negative-space mapping
  04_bridge.py        Cross-kind bridges (gate 5)
  05_temporal.py      Cumulative time-windows (gate 4 — byte-equivalence)
  06_triage.py        Frozen-cluster classifier (gate 6)
  outputs/            New runs land here
fixtures/             Verification anchors (tracked)
cache/                Gitignored — embedder cache + scratch
tests/test_gates.py   Gates 1, 2, 3, 3b
# Foundational, untouched at root:
perspectives.py, toy_minilm.py, toy_gemini.py, sweep.py
```

## Adding an experiment

```python
from core import Corpus, E5InstructEmbedder, Kernel, Query, Readout, run, compare

INSTR = "Group these items by the design concern."
embedder = E5InstructEmbedder(INSTR)

q_dec = Query(
    corpus=Corpus(kinds=("decision",), min_chars=50),
    embedder=embedder, kernel=Kernel(),
    readouts=(Readout("components", {}),),
)
q_thr = Query(
    corpus=Corpus(kinds=("thread",), min_chars=50),
    embedder=embedder, kernel=Kernel(),
    readouts=(Readout("components", {}),),
)
overlap = compare(run(q_dec), run(q_thr), op="intersect")
```

Cache shares between queries — items appearing in both corpora are
embedded once.

## Future-experiment slots

The schema accommodates four open dimensions without modification:

| Hypothesis | How |
|---|---|
| `adversarial-cluster-destruction` | `Kernel(scale_finder=AdversarialSearch(target=…))` |
| `reverse-instruction-inference` | Outer loop over `Embedder(instruction=I)` |
| `multi-instruction-intersection` | Run N `Query` values; `compare(op="intersect")` |
| `cross-corpus` (decisions ∪ code) | New `Corpus.content_source` field + code loader |

## Verification

```bash
# Gates 1, 2, 3, 3b — unit tests (no models, no DB needed)
python tests/test_gates.py

# Gate 4 — byte-equivalence on temporal stratification
python runs/05_temporal.py | diff - fixtures/results_temporal.txt

# Gate 5 — bridge count under concern instruction (= 6)
python runs/04_bridge.py | grep n_bridges_concern

# Gate 6 — triage verdict distribution
#   Requires the same DB+repo state as fixture. Export a path
#   to a project DB if the live worktree DB is too sparse:
STRUCTURE_REVEAL_DB=/path/to/project.db python runs/06_triage.py
```

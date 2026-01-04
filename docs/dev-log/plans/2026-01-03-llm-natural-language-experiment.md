---
status: not-started
updated: 2026-01-03
prereqs:
  - event-topic-property: done
---

# LLM Natural Language Experiment (Round 2)

Test whether **minimal natural language additions** to docstrings reduce LLM exploration overhead without triggering the "complexity signaling" effect observed in experiment 1.

## Background

### Experiment 1 Finding: Complexity Signaling

Formal `Contract:` headers in docstrings backfired on sophisticated models:

| Model | Control Tools | Treatment Tools | Effect |
|-------|---------------|-----------------|--------|
| Opus | 49 | 90 | +84% (worse) |
| Sonnet | 63 | 97 | +54% (worse) |
| Haiku 3.5 | 117 | 94 | -20% (better) |

**Mechanism:** Opus/Sonnet interpreted `Contract: effects=none; idempotent=yes` as a formal specification requiring verification, triggering exhaustive code exploration.

### Feedback-Driven Hypothesis

> "Feed it semantics (stories/descriptions), not syntax (key-value pairs)."

Natural language provides context without triggering formal verification mode:
- **Bad:** `Contract: idempotent=yes`
- **Good:** "Safe to retry."

## Experiment Design

### Conditions

**Control:** Current master docstrings (no modifications)

**Treatment:** Master docstrings + minimal prose additions

### Treatment Docstring Additions

Additions are **one-liners** that answer LLM questions without formal structure:

```python
# Event.log
"""Create a log event.

No side effects. Safe to call multiple times.

Args:
    ...
"""

# Event.progress
"""Create a progress event.

Emit periodically during long operations. Idempotent.

Args:
    ...
"""

# Event.artifact
"""Create an artifact event.

Use for durable outputs. Topic becomes artifact:<type>.

Args:
    ...
"""

# Event.log_signal
"""Create a structured signal event.

Machine-readable. Renderers format distinctly from prose logs.
Use for observations that tooling should parse (not humans).

Args:
    ...
"""
```

### Models

Same lineup for direct comparison:
- claude-opus-4-5-20251101 (sophisticated)
- claude-sonnet-4-20250514 (balanced)
- claude-3-5-haiku-20241022 (efficient)

### Scenarios

Reuse the 5 scenarios from experiment 1:

1. **Discovery** - Find ev API from zero context
2. **Contract Understanding** - Q&A distinguishing related concepts
3. **Signal Usage** - Write code emitting structured events
4. **Error Handling** - Use specific error codes correctly
5. **Integration** - Combine multiple ev concepts

### Runs

**3 runs per scenario per condition per model** (minimum for variance measurement)

Total: 5 scenarios × 2 conditions × 3 models × 3 runs = **90 runs**

## Harness Improvements

### From Experiment 1 Analysis

| Problem | Solution |
|---------|----------|
| Single run per scenario | 3 runs minimum |
| Filename-based metadata parsing | Structured first-line metadata |
| No failure detection | Result validation step |
| No quality assessment | Post-run checklist harness |
| Mixed stdout/stderr | Separate capture |

### New Harness Structure

```
experiments/llm-natural-language/
├── scenarios/
│   ├── 1-discovery.md
│   ├── 2-contract-understanding.md
│   ├── 3-signal-usage.md
│   ├── 4-error-handling.md
│   └── 5-integration.md
├── harness/
│   ├── run-scenario.sh      # Single scenario runner
│   ├── run-experiment.sh    # Full matrix orchestration
│   ├── validate-run.sh      # Post-run validation
│   ├── analyze.py           # Aggregate analysis
│   └── quality-check.py     # Structured quality assessment
├── results/
│   ├── *.jsonl              # Raw run outputs
│   └── *.quality.yaml       # Quality assessments
└── README.md
```

### JSONL Format

First line is metadata (not parsed from filename):

```jsonl
{"type": "run_metadata", "run_id": "exp2-opus-treatment-1-discovery-run1", "model": "claude-opus-4-5-20251101", "condition": "treatment", "scenario": "1-discovery", "run": 1, "timestamp": "2026-01-03T10:30:00Z"}
{"type": "assistant", ...}
{"type": "result", "duration_ms": 12345, "cost_usd": 0.15, ...}
```

### Validation Step

After each run, check:
- [ ] Last line is result object
- [ ] num_turns > 0
- [ ] duration_ms > 0
- [ ] No error status (unless expected)

Mark incomplete runs for manual review or retry.

## Metrics

### Primary (from Exp 1)

- **Tool calls per scenario** - Lower is better
- **Duration in seconds** - For reference only (high variance)
- **Cost in USD** - From result object

### New for Exp 2

- **Tool sequence** - Which tool first/second (reveals strategy)
- **File categories accessed** - code vs docs vs tests
- **Task agent launches** - When/why spawn exploration?
- **Re-reads** - Same file accessed multiple times (redundancy)

### Quality Assessment

Structured checklist per scenario:

```yaml
# quality-check template
run_id: exp2-opus-treatment-1-discovery-run1
scenario: 1-discovery
assessor: human
timestamp: 2026-01-03T11:00:00Z
criteria:
  found_ev_module: true
  identified_factory_methods: true
  understood_event_vs_result: true
  no_hallucinations: true
  task_completed: true
notes: |
  Optional free-form observations
```

## Execution Plan

1. **Setup** - Create feature branch, set up worktree
2. **Treatment Branch** - Apply natural language docstring additions
3. **Harness Build** - Implement improved infrastructure
4. **Dry Run** - Test harness with 1 scenario, 1 model, 1 run
5. **Full Run** - Execute 90-run matrix
6. **Analysis** - Aggregate, compare to experiment 1
7. **Quality Assessment** - Review sample of runs
8. **Document** - Write up findings, update reference docs

## Success Criteria

### Positive Signal

Natural language treatment helps if:
- Opus/Sonnet tool calls **decrease** (reverses exp 1 finding)
- No quality regression in scenario 3 (Sonnet failed with Contract:)
- Haiku 3.5 maintains benefit (doesn't hurt)

### Negative Signal

Abandon approach if:
- Tool calls increase for all models
- Quality decreases (more failures, incomplete tasks)
- No statistically meaningful difference

### Neutral but Informative

If mixed results, document:
- Which models benefit
- Which scenarios show effect
- Capability curve shape

## References

- `docs/dev-log/plans/2026-01-03-event-topic-property.md` - Event.topic implementation
- `feature/llm-first-experiment` branch - Experiment 1 harness and results
- Experiment 1 finding: "Complexity Signaling" effect in formal docstrings

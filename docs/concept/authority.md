# Authority Model

*Who depends on what, and why it matters.*

## The Core Rule

> **Automation must be able to ignore all Events entirely and still make correct decisions based on Result alone.**

This is the fundamental contract. If your CI pipeline, orchestrator, or script needs to branch, retry, alert, or fail — that information must be in `Result`, not in the event stream.

## Three Tiers of Authority

| Tier | Source | Audience | Purpose |
|------|--------|----------|---------|
| **1. Truth** | `Result` | Automation, control flow | Exit codes, success/failure, structured output |
| **2. Telemetry** | `signal`, `metric`, `progress`, `artifact` | Humans, monitoring, UX | Observation, dashboards, audit trails, live displays |
| **3. Narrative** | `log` (prose) | Humans | Explanation, debugging, storytelling |

Only Tier 1 is automation-safe.

## The Mental Model

> **Result** answers "what happened?"
> **Signals** answer "what did we observe along the way?"
> **Logs** answer "how do we explain it?"

## Why This Matters

Many systems accidentally:
- Encode control signals in logs
- Parse stdout for decisions
- Rely on progress output to infer success
- Grep for specific messages to detect errors

This creates brittle automation that breaks when wording changes, events are reordered, or output format evolves.

ev explicitly designs against this:
- **Result** is the *only* authoritative outcome
- **Events** are informational, not contractual

## Tier 1: Result (Truth)

`Result` is the single source of truth for automation:

```python
Result.ok("Deployed 3 stacks", data={"stacks": ["web", "api", "db"]})
Result.error("Connection failed", code=2, data={"host": "db.local"})
```

Automation can safely depend on:
- `result.status` — "ok" or "error"
- `result.code` — exit code (0 = success)
- `result.data` — structured payload for machine consumption

If control flow depends on it, it belongs here.

## Tier 2: Telemetry (Observation)

Events are structured observations for humans and monitoring systems:

```python
Event.log_signal("stack_status", stack="media", healthy=True)
Event.metric("deploy_duration", 23.5, unit="s")
Event.progress("Deploying", step=2, of=3)
Event.artifact("file", path="/tmp/report.pdf")
```

These are useful for:
- Live terminal displays
- Dashboards and monitoring
- Audit trails and replay
- CI log inspection (by humans)
- Debugging after the fact

These are **not** for:
- Pipeline branching
- Retry decisions
- Alerting thresholds (use Result.data for that)
- Any automated decision-making

Think of telemetry as "what we saw" — valuable context, but not the verdict.

## Tier 3: Narrative (Explanation)

Narrative logs are prose for humans:

```python
Event.log("Using cached credentials")
Event.log("Retrying due to transient error", level="warn")
Event.log("Skipping optional validation step")
```

These are:
- Suppressible (`--quiet`)
- Unstable (wording may change)
- Never machine-meaningful

If you find yourself parsing log messages for automation, the contract has failed.

## Practical Implications

### For CLI Authors

When deciding where to put information:

| Question | Answer |
|----------|--------|
| Does the pipeline need this to decide success/failure? | `Result.status` / `Result.code` |
| Does the pipeline need this data for downstream steps? | `Result.data` |
| Should a dashboard show this? | `signal` or `metric` |
| Is this something the user should see during execution? | `signal`, `progress`, or `log` |
| Is this just explaining what's happening? | `log` |

### For Automation Consumers

```python
# CORRECT: Depend only on Result
result = run_command()
if result.status == "ok":
    next_step(result.data["stacks"])
else:
    alert(result.summary)

# WRONG: Parse events for control flow
for event in events:
    if event.signal_name == "deploy_complete":  # Don't do this
        next_step()
```

### For Renderer Authors

Renderers should treat the tiers differently:

| Tier | Rendering Guidance |
|------|-------------------|
| Result | Always show; format for clarity |
| Telemetry | Show in interactive mode; can suppress in quiet mode |
| Narrative | Show by default; suppress freely with `--quiet` |

## The Contract

This rule must hold:

> **If automation can only succeed by inspecting Events, the CLI has a bug.**

The fix is always to move the critical information into `Result`.

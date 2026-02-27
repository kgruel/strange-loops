"""
Loops multi-route computation — Python reference implementation.

Proves routing by kind within a vertex:
  Facts with kind=1 (health) fold into health state (upsert by container).
  Facts with kind=2 (metrics) fold into metrics state (sum cpu values).
  Route by checking fact.kind, apply different fold logic per kind.

All values are integers (u24-compatible) so results match the Bend version.

Container IDs: 1=web, 2=api, 3=db
Kind:          1=health, 2=metrics
Status:        1=ok, 0=down
CPU:           integer percentage (e.g. 50, 80)
"""

# --- Facts: observations with two kinds ---

facts = [
    {"kind": 1, "container": 1, "status": 1},   # web ok
    {"kind": 2, "container": 1, "cpu": 50},      # web cpu 50
    {"kind": 1, "container": 2, "status": 1},   # api ok
    {"kind": 2, "container": 2, "cpu": 80},      # api cpu 80
    {"kind": 1, "container": 3, "status": 1},   # db ok
    {"kind": 2, "container": 3, "cpu": 30},      # db cpu 30
    {"kind": 1, "container": 1, "status": 0},   # web down
    {"kind": 2, "container": 1, "cpu": 90},      # web cpu 90
]

# --- Fold health: upsert latest status per container ---

def fold_health(state, fact):
    new_state = dict(state)
    new_state[fact["container"]] = fact["status"]
    return new_state

# --- Fold metrics: sum cpu values ---

def fold_metrics(state, fact):
    return state + fact["cpu"]

# --- Route by kind, apply correct fold ---

health_state = {}
metrics_state = 0

for fact in facts:
    if fact["kind"] == 1:
        health_state = fold_health(health_state, fact)
    elif fact["kind"] == 2:
        metrics_state = fold_metrics(metrics_state, fact)

# Health total: sum of latest status per container.
# web=0, api=1, db=1 => health_total = 2
health_total = sum(health_state.values())

# Metrics total: sum of all cpu values.
# 50 + 80 + 30 + 90 = 250
metrics_total = metrics_state

# Combined result
result = health_total + metrics_total
print(result)
# => 252

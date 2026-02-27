"""
Loops fold computation — Python reference implementation.

Proves the core loops model:
  Facts flow in -> fold accumulates state -> boundary fires -> Tick emits.

All values are integers (u24-compatible) so results match the Bend version.

Container IDs: 1=web, 2=api, 3=db
Kind:          1=health
Status:        1=ok, 0=down
"""

# --- Facts: observations about container health ---

facts = [
    {"kind": 1, "container": 1, "status": 1},  # web ok
    {"kind": 1, "container": 2, "status": 1},  # api ok
    {"kind": 1, "container": 1, "status": 0},  # web down
    {"kind": 1, "container": 3, "status": 1},  # db ok
    {"kind": 1, "container": 1, "status": 1},  # web ok again
    {"kind": 1, "container": 2, "status": 1},  # api ok
]

# --- Fold: accumulate latest status per container ---

def fold(state, fact):
    """Upsert: set state[container] = status. Returns new state."""
    new_state = dict(state)
    new_state[fact["container"]] = fact["status"]
    return new_state

# --- Boundary: all 3 containers have reported ---

EXPECTED_CONTAINERS = {1, 2, 3}

def boundary(state):
    return set(state.keys()) == EXPECTED_CONTAINERS

# --- Run the loop ---

state = {}
for fact in facts:
    state = fold(state, fact)
    if boundary(state):
        # Sum all status values — the tick payload
        tick_payload = sum(state.values())
        # Don't break: keep folding (last boundary wins, like real loops)

# The tick payload is the sum of the latest status for each container.
# web=1, api=1, db=1 => tick_payload = 3
print(tick_payload)

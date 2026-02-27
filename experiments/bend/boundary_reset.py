"""
Loops boundary-reset computation — Python reference implementation.

Proves the core CYCLE: fold until boundary, emit tick, reset state, keep folding.

A stream of health facts arrives. After every 3 facts of kind=1 (health),
the boundary fires: emit a tick (sum of status values), reset state, continue.

Multiple ticks are emitted from one pass through the facts.

Container IDs: 1=web, 2=api, 3=db
Kind:          1=health
Status:        1=ok, 0=down

Output: (tick_count, last_tick_payload)
"""

# --- Facts: a longer stream to trigger multiple boundaries ---

facts = [
    # Batch 1: 3 health reports -> boundary fires
    {"kind": 1, "container": 1, "status": 1},  # web ok
    {"kind": 1, "container": 2, "status": 1},  # api ok
    {"kind": 1, "container": 3, "status": 1},  # db ok
    # Batch 2: 3 more -> boundary fires again
    {"kind": 1, "container": 1, "status": 0},  # web down
    {"kind": 1, "container": 2, "status": 1},  # api ok
    {"kind": 1, "container": 3, "status": 0},  # db down
    # Batch 3: 3 more -> boundary fires again
    {"kind": 1, "container": 1, "status": 1},  # web ok
    {"kind": 1, "container": 2, "status": 1},  # api ok
    {"kind": 1, "container": 3, "status": 1},  # db ok
]

# --- Fold with boundary and reset ---

BOUNDARY_COUNT = 3  # fire after every 3 facts

state = {}
count = 0
ticks = []

for fact in facts:
    state[fact["container"]] = fact["status"]
    count += 1
    if count == BOUNDARY_COUNT:
        # Boundary fires: emit tick
        tick_payload = sum(state.values())
        ticks.append(tick_payload)
        # Reset state
        state = {}
        count = 0

tick_count = len(ticks)
last_tick_payload = ticks[-1] if ticks else 0

# Encode as single number: tick_count * 1000 + last_tick_payload
# Batch 1: 1+1+1 = 3
# Batch 2: 0+1+0 = 1
# Batch 3: 1+1+1 = 3
# tick_count = 3, last_tick_payload = 3
# result = 3 * 1000 + 3 = 3003
result = tick_count * 1000 + last_tick_payload
print(result)

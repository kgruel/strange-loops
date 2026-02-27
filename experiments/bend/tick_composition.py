"""
Loops tick-composition computation — Python reference implementation.

Proves compositional power: ticks from one loop become facts for another.

Stage 1: Fold health facts per batch of 3 -> emit tick with health summary.
          Tick payload = sum of latest status per container.
          "All healthy" = payload of 3 (all three containers ok).

Stage 2: Take tick payloads, feed as facts to a second fold.
          Second fold counts how many ticks had all-healthy status (payload == 3).

Container IDs: 1=web, 2=api, 3=db
Kind:          1=health
Status:        1=ok, 0=down

Output: count of all-healthy ticks from stage 2
"""

# --- Facts: a stream triggering multiple ticks ---

facts = [
    # Batch 1: all ok -> tick payload 3 (all healthy)
    {"kind": 1, "container": 1, "status": 1},
    {"kind": 1, "container": 2, "status": 1},
    {"kind": 1, "container": 3, "status": 1},
    # Batch 2: one down -> tick payload 2 (not all healthy)
    {"kind": 1, "container": 1, "status": 0},
    {"kind": 1, "container": 2, "status": 1},
    {"kind": 1, "container": 3, "status": 1},
    # Batch 3: all ok -> tick payload 3 (all healthy)
    {"kind": 1, "container": 1, "status": 1},
    {"kind": 1, "container": 2, "status": 1},
    {"kind": 1, "container": 3, "status": 1},
    # Batch 4: two down -> tick payload 1 (not all healthy)
    {"kind": 1, "container": 1, "status": 0},
    {"kind": 1, "container": 2, "status": 0},
    {"kind": 1, "container": 3, "status": 1},
    # Batch 5: all ok -> tick payload 3 (all healthy)
    {"kind": 1, "container": 1, "status": 1},
    {"kind": 1, "container": 2, "status": 1},
    {"kind": 1, "container": 3, "status": 1},
]

# --- Stage 1: fold facts, emit ticks at boundary ---

BOUNDARY_COUNT = 3

state = {}
count = 0
tick_payloads = []

for fact in facts:
    state[fact["container"]] = fact["status"]
    count += 1
    if count == BOUNDARY_COUNT:
        tick_payload = sum(state.values())
        tick_payloads.append(tick_payload)
        state = {}
        count = 0

# tick_payloads = [3, 2, 3, 1, 3]

# --- Stage 2: fold tick payloads, count all-healthy ---

all_healthy_count = 0
for payload in tick_payloads:
    if payload == 3:
        all_healthy_count += 1

# 3 ticks had all-healthy status (batches 1, 3, 5)
print(all_healthy_count)
# => 3

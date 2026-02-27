# Loops boundary-reset computation — Bend implementation.
#
# Same computation as boundary_reset.py, on interaction combinators.
#
# Proves the core CYCLE: fold until boundary, emit tick, reset, keep folding.
#
# After every 3 health facts, boundary fires:
#   emit tick (sum of status values), reset state, continue.
#
# Container IDs: 1=web, 2=api, 3=db
# Kind:          1=health
# Status:        1=ok, 0=down
#
# Output: tick_count * 1000 + last_tick_payload

object Fact { kind, container, status }

# Sum status values for containers 1, 2, 3 in the map.
def tick_payload(state):
  v1 = state[1]
  v2 = state[2]
  v3 = state[3]
  return v1 + v2 + v3

# Process facts with boundary detection and state reset.
# count: how many facts since last reset
# state: current health map
# tick_count: how many ticks emitted so far
# last_payload: payload of the most recent tick
def cycle(facts, count, state, tick_count, last_payload):
  match facts:
    case List/Cons:
      open Fact: facts.head
      # Fold: upsert container status
      state[facts.head.container] = facts.head.status
      new_count = count + 1
      # Boundary: every 3 facts
      if new_count == 3:
        payload = tick_payload(state)
        # Reset state, increment tick count
        return cycle(facts.tail, 0, {}, tick_count + 1, payload)
      else:
        return cycle(facts.tail, new_count, state, tick_count, last_payload)
    case List/Nil:
      # Encode result: tick_count * 1000 + last_payload
      return tick_count * 1000 + last_payload

def main():
  facts = [
    # Batch 1: 3 health reports -> tick (1+1+1=3)
    Fact { kind: 1, container: 1, status: 1 },
    Fact { kind: 1, container: 2, status: 1 },
    Fact { kind: 1, container: 3, status: 1 },
    # Batch 2: 3 more -> tick (0+1+0=1)
    Fact { kind: 1, container: 1, status: 0 },
    Fact { kind: 1, container: 2, status: 1 },
    Fact { kind: 1, container: 3, status: 0 },
    # Batch 3: 3 more -> tick (1+1+1=3)
    Fact { kind: 1, container: 1, status: 1 },
    Fact { kind: 1, container: 2, status: 1 },
    Fact { kind: 1, container: 3, status: 1 }
  ]

  return cycle(facts, 0, {}, 0, 0)

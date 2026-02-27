# Loops tick-composition computation — Bend implementation.
#
# Same computation as tick_composition.py, on interaction combinators.
#
# Proves compositional power: ticks from one loop become facts for another.
#
# Stage 1: Fold health facts in batches of 3 -> emit tick payloads.
# Stage 2: Fold tick payloads -> count how many had all-healthy status (==3).
#
# Container IDs: 1=web, 2=api, 3=db
# Kind:          1=health
# Status:        1=ok, 0=down

object Fact { kind, container, status }

# Sum status values for containers 1, 2, 3 in the map.
def compute_payload(state):
  v1 = state[1]
  v2 = state[2]
  v3 = state[3]
  return v1 + v2 + v3

# Stage 1: Process facts, emit tick payloads as a list.
# Returns a List of u24 tick payloads.
def stage1(facts, count, state):
  match facts:
    case List/Cons:
      open Fact: facts.head
      state[facts.head.container] = facts.head.status
      new_count = count + 1
      if new_count == 3:
        payload = compute_payload(state)
        # Emit tick payload, reset state, continue
        rest = stage1(facts.tail, 0, {})
        return List/Cons(payload, rest)
      else:
        return stage1(facts.tail, new_count, state)
    case List/Nil:
      return List/Nil

# Stage 2: Fold tick payloads, count all-healthy (payload == 3).
def stage2(ticks, acc):
  match ticks:
    case List/Cons:
      if ticks.head == 3:
        return stage2(ticks.tail, acc + 1)
      else:
        return stage2(ticks.tail, acc)
    case List/Nil:
      return acc

def main():
  facts = [
    # Batch 1: all ok -> payload 3
    Fact { kind: 1, container: 1, status: 1 },
    Fact { kind: 1, container: 2, status: 1 },
    Fact { kind: 1, container: 3, status: 1 },
    # Batch 2: one down -> payload 2
    Fact { kind: 1, container: 1, status: 0 },
    Fact { kind: 1, container: 2, status: 1 },
    Fact { kind: 1, container: 3, status: 1 },
    # Batch 3: all ok -> payload 3
    Fact { kind: 1, container: 1, status: 1 },
    Fact { kind: 1, container: 2, status: 1 },
    Fact { kind: 1, container: 3, status: 1 },
    # Batch 4: two down -> payload 1
    Fact { kind: 1, container: 1, status: 0 },
    Fact { kind: 1, container: 2, status: 0 },
    Fact { kind: 1, container: 3, status: 1 },
    # Batch 5: all ok -> payload 3
    Fact { kind: 1, container: 1, status: 1 },
    Fact { kind: 1, container: 2, status: 1 },
    Fact { kind: 1, container: 3, status: 1 }
  ]

  # Stage 1: fold facts into tick payloads
  ticks = stage1(facts, 0, {})

  # Stage 2: fold ticks, count all-healthy
  return stage2(ticks, 0)

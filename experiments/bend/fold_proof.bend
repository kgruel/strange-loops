# Loops fold computation — Bend implementation.
#
# Same computation as fold_proof.py, on interaction combinators.
#
# Facts flow in -> fold accumulates state -> boundary fires -> Tick emits.
#
# Container IDs: 1=web, 2=api, 3=db
# Kind:          1=health
# Status:        1=ok, 0=down

# A Fact is an observation: kind, container id, status.
object Fact { kind, container, status }

# Fold a single fact into state (a Map keyed by container id).
# Upsert: state[container] = status.
def fold_fact(state, fact):
  open Fact: fact
  state[fact.container] = fact.status
  return state

# Left-fold a list of facts into accumulated state.
def fold_facts(facts, state):
  match facts:
    case List/Cons:
      return fold_facts(facts.tail, fold_fact(state, facts.head))
    case List/Nil:
      return state

# Boundary check: have all 3 containers reported?
# We check by looking up keys 1, 2, 3 in the map.
# Map/contains returns (u24, Map) where the u24 is 0 or 1.
def boundary(state):
  (has1, state) = Map/contains(state, 1)
  (has2, state) = Map/contains(state, 2)
  (has3, state) = Map/contains(state, 3)
  return has1 & has2 & has3

# Extract the tick payload: sum of status values for containers 1, 2, 3.
def tick_payload(state):
  v1 = state[1]
  v2 = state[2]
  v3 = state[3]
  return v1 + v2 + v3

def main():
  # The facts — same sequence as the Python version.
  facts = [
    Fact { kind: 1, container: 1, status: 1 },
    Fact { kind: 1, container: 2, status: 1 },
    Fact { kind: 1, container: 1, status: 0 },
    Fact { kind: 1, container: 3, status: 1 },
    Fact { kind: 1, container: 1, status: 1 },
    Fact { kind: 1, container: 2, status: 1 }
  ]

  # Fold all facts into state (start with empty map).
  state = fold_facts(facts, {})

  # Check boundary, emit tick if all containers reported.
  if boundary(state) == 1:
    return tick_payload(state)
  else:
    return 0

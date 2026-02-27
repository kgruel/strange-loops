# Loops multi-route computation — Bend implementation.
#
# Same computation as multi_route.py, on interaction combinators.
#
# Proves routing by kind within a vertex:
#   Facts with kind=1 (health) fold into health state (upsert by container).
#   Facts with kind=2 (metrics) fold into metrics state (sum cpu values).
#
# Container IDs: 1=web, 2=api, 3=db
# Kind:          1=health, 2=metrics
# Status:        1=ok, 0=down
# CPU:           integer percentage

# A Fact carries kind and a value field.
# For health: value = status (1=ok, 0=down)
# For metrics: value = cpu percentage
object Fact { kind, container, value }

# Route and fold a list of facts into (health_map, metrics_sum).
# health_map: Map keyed by container id, value = latest status
# metrics_sum: running total of cpu values
def route_fold(facts, health, metrics):
  match facts:
    case List/Cons:
      open Fact: facts.head
      if facts.head.kind == 1:
        # Health: upsert container status
        health[facts.head.container] = facts.head.value
        return route_fold(facts.tail, health, metrics)
      else:
        # Metrics: sum cpu values
        return route_fold(facts.tail, health, metrics + facts.head.value)
    case List/Nil:
      return (health, metrics)

# Extract health total: sum of status values for containers 1, 2, 3.
def health_total(health):
  v1 = health[1]
  v2 = health[2]
  v3 = health[3]
  return v1 + v2 + v3

def main():
  facts = [
    Fact { kind: 1, container: 1, value: 1 },
    Fact { kind: 2, container: 1, value: 50 },
    Fact { kind: 1, container: 2, value: 1 },
    Fact { kind: 2, container: 2, value: 80 },
    Fact { kind: 1, container: 3, value: 1 },
    Fact { kind: 2, container: 3, value: 30 },
    Fact { kind: 1, container: 1, value: 0 },
    Fact { kind: 2, container: 1, value: 90 }
  ]

  (health, metrics) = route_fold(facts, {}, 0)
  ht = health_total(health)
  return ht + metrics

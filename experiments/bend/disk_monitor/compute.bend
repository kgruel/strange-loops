# Disk monitor — compute core on interaction combinators.
#
# Reads facts from stdin (emitted by witness.sh), folds into state,
# checks boundary, emits tick payload. No I/O except the pipe.
#
# Wire format: "kind mount_id pct" per line
#   kind=1: fold into state (state[mount_id] = pct)
#   kind=2: boundary signal — stop reading, emit tick
#
# Mount IDs: 1=/, 2=VM, 3=Preboot, 4=Data, 5=/nix
# Tick payload: max(pct) across all mounts

# --- Parsing ---

# Decimal string → u24. Folds chars: acc = acc * 10 + (c - '0')
def parse_u24(s):
  acc = 0
  fold s with acc:
    case String/Cons:
      return s.tail(acc * 10 + (s.head - 48))
    case String/Nil:
      return acc

# Nth element of a list (0-indexed).
def list_get(xs, n):
  match xs:
    case List/Cons:
      if n == 0:
        return xs.head
      else:
        return list_get(xs.tail, n - 1)
    case List/Nil:
      return ""

# --- Fold / Boundary / Tick ---

def max2(a, b):
  if a > b:
    return a
  else:
    return b

# All 5 mounts present?
def boundary(state):
  (has1, state) = Map/contains(state, 1)
  (has2, state) = Map/contains(state, 2)
  (has3, state) = Map/contains(state, 3)
  (has4, state) = Map/contains(state, 4)
  (has5, state) = Map/contains(state, 5)
  return has1 & has2 & has3 & has4 & has5

# max(pct) across all mounts.
def tick_payload(state):
  v1 = state[1]
  v2 = state[2]
  v3 = state[3]
  v4 = state[4]
  v5 = state[5]
  return max2(max2(max2(v1, v2), max2(v3, v4)), v5)

# --- IO loop ---

# Read lines, parse facts, fold into state. Stop at kind=2.
def fold_loop(state):
  with IO:
    result <- IO/input()
    match result:
      case Result/Ok:
        line = result.val
        parts = String/split(line, ' ')
        kind = parse_u24(list_get(parts, 0))
        if kind == 1:
          mount_id = parse_u24(list_get(parts, 1))
          pct = parse_u24(list_get(parts, 2))
          state[mount_id] = pct
          final <- fold_loop(state)
          return wrap(final)
        else:
          return wrap(state)
      case Result/Err:
        return wrap(state)

def main():
  with IO:
    state <- fold_loop({})
    if boundary(state) == 1:
      tick = tick_payload(state)
      * <- IO/print(u24/to_string(tick))
      * <- IO/print("\n")
      return wrap(0)
    else:
      * <- IO/print("0\n")
      return wrap(0)

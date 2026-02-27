# Reader feed aggregation — compute core on interaction combinators.
#
# Reads facts from stdin (emitted by witness.sh), deduplicates items
# by link hash, counts unique items, emits tick payload.
#
# Wire format: "kind feed_id value" per line
#   kind=1: item fact (value = link_hash for dedup)
#   kind=2: per-feed boundary (value = item_count from witness)
#   kind=3: global boundary — stop reading, emit tick
#
# Tick payload: unique item count (u24).

# --- Parsing (reused from disk_monitor) ---

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

# --- IO loop ---

# Read lines, parse facts, fold into state. Stop at kind=3.
# Deduplicates items by link_hash, counts unique insertions.
#
# Three arguments through the fold:
#   items      — Map of link_hash → 1 (dedup set)
#   count      — u24, number of unique items seen
#   feeds_done — Map of feed_id → 1 (completed feeds)
def fold_loop(items, count, feeds_done):
  with IO:
    result <- IO/input()
    match result:
      case Result/Ok:
        line = result.val
        parts = String/split(line, ' ')
        kind = parse_u24(list_get(parts, 0))
        if kind == 1:
          link_hash = parse_u24(list_get(parts, 2))
          (has, items) = Map/contains(items, link_hash)
          if has == 1:
            # Already seen this link — skip
            final <- fold_loop(items, count, feeds_done)
            return wrap(final)
          else:
            # New item — insert and increment
            items[link_hash] = 1
            final <- fold_loop(items, count + 1, feeds_done)
            return wrap(final)
        else:
          if kind == 2:
            feed_id = parse_u24(list_get(parts, 1))
            feeds_done[feed_id] = 1
            final <- fold_loop(items, count, feeds_done)
            return wrap(final)
          else:
            # kind=3: global boundary — stop
            return wrap(count)
      case Result/Err:
        return wrap(count)

def main():
  with IO:
    count <- fold_loop({}, 0, {})
    * <- IO/print(u24/to_string(count))
    * <- IO/print("\n")
    return wrap(0)

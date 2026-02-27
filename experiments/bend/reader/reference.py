"""
Reader feed aggregation — Python reference. Reads same wire format as compute.bend.

Wire format on stdin: "kind feed_id value" per line
  kind=1: item fact (value = link_hash)
  kind=2: per-feed boundary (value = item_count)
  kind=3: global boundary — stop
"""
import sys

state = {}  # link_hash → 1 (dedup set)
for line in sys.stdin:
    parts = line.strip().split()
    kind = int(parts[0])
    if kind == 1:
        link_hash = int(parts[2])
        state[link_hash] = 1
    elif kind == 3:
        break

print(len(state))

"""
Disk monitor — Python reference. Reads same wire format as compute.bend.

Wire format on stdin: "kind mount_id pct" per line
  kind=1: fold into state
  kind=2: boundary signal
"""
import sys

state = {}
for line in sys.stdin:
    kind, mount_id, pct = (int(x) for x in line.strip().split())
    if kind == 1:
        state[mount_id] = pct
    else:
        break

if set(state.keys()) == {1, 2, 3, 4, 5}:
    print(max(state.values()))
else:
    print(0)

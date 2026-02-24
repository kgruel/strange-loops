#!/usr/bin/env python3
import os
import sys
from pathlib import Path


STATE_PATH = Path(__file__).resolve().parent / "data" / "feeds.db"


def hash_string(text: str) -> int:
    acc = 0
    for ch in text:
        acc = (acc * 31 + ord(ch)) & 0xFFFFFF  # u24 wrapping
    return acc


def load_state() -> set[int]:
    try:
        raw = STATE_PATH.read_text("ascii")
    except FileNotFoundError:
        return set()
    except OSError:
        # Treat unreadable state as empty for this exploratory experiment.
        return set()

    keys: set[int] = set()
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            keys.add(int(line, 10) & 0xFFFFFF)
        except ValueError:
            continue
    return keys


def save_state(keys: set[int]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = "".join(f"{k}\n" for k in sorted(keys))
    tmp = f"{STATE_PATH}.tmp"
    Path(tmp).write_text(data, "ascii")
    os.replace(tmp, STATE_PATH)


def main() -> int:
    keys = load_state()
    total_before = len(keys)

    new = 0
    for raw in sys.stdin:
        line = raw.rstrip("\n")
        if not line or line.startswith("#"):
            continue
        h = hash_string(line)
        if h not in keys:
            keys.add(h)
            new += 1

    save_state(keys)
    total_after = len(keys)
    # Match Bend's `(new, total)` style output.
    print((new, total_after))
    # A sanity guard: total should never shrink.
    if total_after < total_before:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

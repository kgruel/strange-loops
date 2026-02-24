#!/usr/bin/env python3
import sys


def hash_string(text: str) -> int:
    acc = 0
    for ch in text:
        acc = (acc * 31 + ord(ch)) & 0xFFFFFF  # u24 wrapping
    return acc


def main() -> int:
    seen: set[int] = set()
    for raw in sys.stdin:
        line = raw.rstrip("\n")
        if not line or line.startswith("#"):
            continue
        seen.add(hash_string(line))
    print(len(seen))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

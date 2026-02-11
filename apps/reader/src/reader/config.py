"""Resolve vars from environment for vertex template substitution."""

import os


def resolve_vars() -> dict[str, str]:
    return {
        "hn_username": os.environ.get("HN_USERNAME", ""),
    }

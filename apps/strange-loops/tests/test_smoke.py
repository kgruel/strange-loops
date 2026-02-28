"""Smoke test — verify package imports and CLI entry point exist."""

from __future__ import annotations


def test_import():
    import strange_loops  # noqa: F401


def test_cli_entry():
    from strange_loops.cli import main

    assert callable(main)

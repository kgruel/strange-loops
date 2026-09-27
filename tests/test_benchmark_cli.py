"""The cold-start benchmark must use a supported, target-free JSON-client command."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def benchmark(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "_benchmark_cli_test", ROOT / "benchmarks/characterize.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("returncode", [0, 2])
def test_cli_probe_uses_json_client_help(benchmark, monkeypatch, returncode):
    calls = []
    measured = []
    sentinel = object()

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, returncode, "", "probe refused")

    def measure(name, layer, depth, operation, samples):
        measured.append((name, layer, depth, samples))
        operation()
        return sentinel

    monkeypatch.setattr(benchmark.subprocess, "run", run)
    monkeypatch.setattr(benchmark, "measure", measure)
    if returncode:
        with pytest.raises(benchmark.ProbeError, match="exited 2"):
            benchmark.probe_cli()
    else:
        assert benchmark.probe_cli() == [sentinel]
    assert calls == [["uv", "run", "loops-min", "--help"]]
    assert measured == [("cli_cold_help", "cli", 0, 5)]
    assert benchmark.INSTRUMENT_VERSION == "2"


def test_changed_probe_is_not_comparable_to_old_instrument(benchmark):
    with pytest.raises(SystemExit, match="probes do not mean the same thing"):
        benchmark.compare_arms(
            {"instrument_version": "1"},
            {"instrument_version": benchmark.INSTRUMENT_VERSION},
            [],
        )

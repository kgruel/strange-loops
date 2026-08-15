"""Characterization ledger — what the core costs, and how that cost scales.

This is an instrument, not a gate. It answers "what does an operation cost at
this store depth, and what shape does that cost have as the store grows" — the
question you ask *before* building a layer on top of something, not the question
you ask on every PR.

Two design commitments, both learned the hard way:

1.  **Scaling over point latency.** A single measurement at n=500 cannot see an
    O(n) operation. Every depth-sensitive probe is measured across a sweep, and
    the ledger reports the curve. What foot-guns you later is complexity class,
    not a constant factor.

2.  **The instrument states its own resolution.** Absolute numbers from a laptop
    cannot honestly resolve a 10% drift. Run the reference arm twice around the
    candidate (``--bracket``) and the comparison computes the session's *measured*
    noise floor, then refuses to call a delta real unless it clears that floor.
    A resolution that is measured beats one that is asserted.

Usage::

    # Characterize this checkout, writing a machine-readable arm
    uv run python benchmarks/characterize.py --record arm-main.json

    # Compare two arms, with a bracket repeat establishing the noise floor
    uv run python benchmarks/characterize.py --compare arm-main.json arm-sdk.json \
        --bracket arm-main-repeat.json

Comparisons are only valid within one INSTRUMENT_VERSION, on one machine, in one
sitting. The comparison path enforces the first and warns loudly on the second.
"""

import argparse
import json
import platform
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from atoms import Fact
from engine import open_vertex, vertex_read, vertex_reindex
from engine.handle import WriteCredentials
from engine.sqlite_store import SqliteStore
from engine.store_reader import StoreReader

# Bump when a probe's *meaning* changes (what it measures, not how fast it is).
# Arms recorded under different instrument versions are not comparable.
INSTRUMENT_VERSION = "1"

DEFAULT_DEPTHS = (1_000, 10_000, 100_000)

# A probe that takes longer than this per sample drops to MIN_SAMPLES so a deep
# sweep still finishes. Recorded in the output as the actual `n`.
EXPENSIVE_SAMPLE_MS = 50.0
DEFAULT_SAMPLES = 25
MIN_SAMPLES = 3

SEARCH_TOKEN = "zarquon"


class BenchCredentials:
    """Unsigned write credentials — the ledger measures the core, not signing."""

    def for_write(self, vertex: Path) -> WriteCredentials:
        return WriteCredentials()


@dataclass(frozen=True)
class Sample:
    """One probe's measured cost distribution at one store depth."""

    probe: str
    layer: str
    depth: int
    unit: str
    n: int
    median: float
    minimum: float
    p95: float

    @property
    def key(self) -> str:
        return f"{self.probe}@{self.depth}"


def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile — no interpolation, honest for small n."""
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(round(pct / 100.0 * len(ordered)))))
    return ordered[rank - 1]


def measure(
    probe: str,
    layer: str,
    depth: int,
    operation: Callable[[], Any],
    samples: int = DEFAULT_SAMPLES,
) -> Sample:
    """Time `operation` repeatedly, adapting sample count to observed cost.

    The first sample decides the budget: cheap probes get the full run, expensive
    ones drop to MIN_SAMPLES so a 100k-depth sweep still terminates. The actual
    count lands in the ledger so a reader can weigh the dispersion.
    """
    timings: list[float] = []

    start = time.perf_counter()
    operation()
    timings.append((time.perf_counter() - start) * 1000)

    budget = MIN_SAMPLES if timings[0] > EXPENSIVE_SAMPLE_MS else samples
    for _ in range(budget - 1):
        start = time.perf_counter()
        operation()
        timings.append((time.perf_counter() - start) * 1000)

    return Sample(
        probe=probe,
        layer=layer,
        depth=depth,
        unit="ms",
        n=len(timings),
        median=round(statistics.median(timings), 4),
        minimum=round(min(timings), 4),
        p95=round(_percentile(timings, 95), 4),
    )


def _fact(index: int) -> Fact:
    return Fact(
        kind="note",
        ts=1_700_000_000.0 + index,
        payload={"index": index, "content": f"characterization note {index} {SEARCH_TOKEN}"},
        observer="ledger",
        origin="ledger",
    )


def _write_vertex_file(vertex_path: Path, store_path: Path, name: str) -> None:
    """A vertex declaring one folded, searchable kind.

    ``search "content"`` is load-bearing: FTS covers only kinds the declaration
    marks searchable, so without it every search probe would scan an empty index
    and report a very fast nothing.
    """
    vertex_path.write_text(
        f'name "{name}"\n'
        f'store "{store_path}"\n'
        f"loops {{\n"
        f"  note {{\n"
        f'    fold {{ items "collect" 100 }}\n'
        f'    search "content"\n'
        f"  }}\n"
        f"}}\n"
    )


def _new_store(store_path: Path) -> SqliteStore:
    return SqliteStore(
        path=store_path,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )


# --------------------------------------------------------------------------
# Layer: raw store
# --------------------------------------------------------------------------


def probe_store(depth: int) -> list[Sample]:
    """Raw SqliteStore append and full-scan cost at `depth` existing rows."""
    samples: list[Sample] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        store_path = Path(tmpdir) / "ledger.db"
        store = _new_store(store_path)
        for i in range(depth):
            store.append(_fact(i))

        samples.append(
            measure("store_scan_all", "store", depth, lambda: _assert_len(store.since(0), depth))
        )

        counter = iter(range(depth, depth + DEFAULT_SAMPLES + 1))
        samples.append(
            measure("store_append", "store", depth, lambda: store.append(_fact(next(counter))))
        )
        store.close()
    return samples


def _assert_len(rows: list[Any], expected: int) -> None:
    """A read that returns nothing is not a fast read — it is a broken probe."""
    if len(rows) != expected:
        raise ProbeError(f"expected {expected} rows from the store, saw {len(rows)}")


class ProbeError(RuntimeError):
    """A probe could not measure what it claims to measure."""


# --------------------------------------------------------------------------
# Layers: engine and sdk, sharing one filled vertex per depth
# --------------------------------------------------------------------------


def probe_vertex_layers(depth: int, include_sdk: bool) -> list[Sample]:
    """Engine and (when present) sdk probes against one vertex filled to `depth`.

    Filling happens through a *held* handle so the fill cost is the engine's
    receive, not repeated opens — the open cost is then measured separately and
    the two can be told apart. Read probes run before write probes so reads see
    exactly `depth` facts.
    """
    samples: list[Sample] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        store_path = Path(tmpdir) / "ledger.db"
        vertex_path = Path(tmpdir) / "ledger.vertex"
        _write_vertex_file(vertex_path, store_path, "ledger")
        _new_store(store_path).close()

        credentials = BenchCredentials()
        with open_vertex(vertex_path, credentials=credentials) as handle:
            for i in range(depth):
                handle.receive(_fact(i))

        # --- engine reads (store untouched) ---
        reader = StoreReader(store_path)
        samples.append(
            measure(
                "engine_summary",
                "engine",
                depth,
                lambda: _assert_total(reader.summary(), depth),
            )
        )
        samples.append(
            measure(
                "engine_replay_fold",
                "engine",
                depth,
                lambda: _assert_replayed(vertex_read(vertex_path)),
            )
        )
        samples.append(
            measure(
                "engine_open_vertex_cold",
                "engine",
                depth,
                lambda: _open_and_close(vertex_path, credentials),
            )
        )

        # Full drop+rebuild of the derived FTS index. Writes no facts, so it
        # leaves depth intact — but it must run before any search probe, since
        # receive does not maintain FTS and reindex is its only writer.
        samples.append(
            measure(
                "engine_reindex_fts",
                "engine",
                depth,
                lambda: vertex_reindex(vertex_path),
            )
        )

        # --- sdk reads (store untouched) ---
        if include_sdk:
            samples.extend(_probe_sdk_reads(vertex_path, depth))

        # --- writes, held handle: isolates receive from open ---
        with open_vertex(vertex_path, credentials=credentials) as handle:
            counter = iter(range(depth, depth + DEFAULT_SAMPLES + 1))
            samples.append(
                measure(
                    "engine_receive_held",
                    "engine",
                    depth,
                    lambda: handle.receive(_fact(next(counter))),
                )
            )

        if include_sdk:
            samples.append(_probe_sdk_emit(vertex_path, depth))

    return samples


def _open_and_close(vertex_path: Path, credentials: BenchCredentials) -> None:
    handle = open_vertex(vertex_path, credentials=credentials)
    handle.close()


def _assert_total(summary: dict[str, Any], expected: int) -> None:
    total = summary["facts"]["total"]
    if total != expected:
        raise ProbeError(f"summary reported {total} facts, expected {expected}")


def _assert_replayed(state: dict[str, Any]) -> None:
    if "note" not in state:
        raise ProbeError("fold replay produced no 'note' state — probe is measuring nothing")


def _probe_sdk_reads(vertex_path: Path, depth: int) -> list[Sample]:
    from sdk import read_facts, read_summary, search_facts

    samples = [
        measure(
            "sdk_read_summary",
            "sdk",
            depth,
            lambda: _assert_fact_total(read_summary(vertex_path), depth),
        ),
        measure(
            "sdk_read_page_100",
            "sdk",
            depth,
            lambda: _assert_page(read_facts(vertex_path, limit=100), 100),
        ),
        measure(
            "sdk_search",
            "sdk",
            depth,
            lambda: _assert_hits(search_facts(vertex_path, query=SEARCH_TOKEN)),
        ),
    ]
    return samples


def _probe_sdk_emit(vertex_path: Path, depth: int) -> Sample:
    from sdk import emit_fact

    counter = iter(range(depth, depth + DEFAULT_SAMPLES + 1))

    def one_emit() -> None:
        index = next(counter)
        emit_fact(
            vertex_path,
            "note",
            {"index": index, "content": f"characterization note {index} {SEARCH_TOKEN}"},
            observer="ledger",
            admit_undeclared=True,
        )

    return measure("sdk_emit_fact", "sdk", depth, one_emit)


def _assert_fact_total(summary: Any, expected: int) -> None:
    if summary.fact_total != expected:
        raise ProbeError(f"sdk summary reported {summary.fact_total} facts, expected {expected}")


def _assert_page(page: Any, expected: int) -> None:
    if len(page.items) != expected:
        raise ProbeError(f"sdk page returned {len(page.items)} items, expected {expected}")


def _assert_hits(result: Any) -> None:
    """A search that matches nothing would otherwise look like a very fast search."""
    if len(result.matches) == 0:
        raise ProbeError(
            f"sdk search for {result.query!r} matched zero facts — measuring an empty scan"
        )


# --------------------------------------------------------------------------
# Layer: CLI cold start (depth-independent)
# --------------------------------------------------------------------------


def probe_cli() -> list[Sample]:
    """Cold `loops --version` invocation. A failing CLI raises rather than scoring 0.0."""

    def one_invocation() -> None:
        result = subprocess.run(
            ["uv", "run", "loops", "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ProbeError(
                f"`loops --version` exited {result.returncode}: {result.stderr.strip()[:200]}"
            )

    return [measure("cli_cold_version", "cli", 0, one_invocation, samples=5)]


# --------------------------------------------------------------------------
# Environment capture — provenance is half the point of a ledger
# --------------------------------------------------------------------------


def _shell(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def capture_environment() -> dict[str, Any]:
    """Everything a future reader needs to know whether their run is comparable."""
    cpu = None
    power = None
    if sys.platform == "darwin":
        cpu = _shell(["sysctl", "-n", "machdep.cpu.brand_string"])
        battery = _shell(["pmset", "-g", "batt"])
        if battery:
            power = "AC" if "AC Power" in battery else "battery"
    elif sys.platform.startswith("linux"):
        cpu = _shell(["bash", "-lc", "grep -m1 'model name' /proc/cpuinfo | cut -d: -f2"])

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "cpu": cpu or platform.processor() or "unknown",
        "power_source": power or "unknown",
        "python": sys.version.split()[0],
        "git_commit": _shell(["git", "rev-parse", "HEAD"]),
        "git_describe": _shell(["git", "describe", "--always", "--dirty"]),
        "git_branch": _shell(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
    }


# --------------------------------------------------------------------------
# Arm assembly
# --------------------------------------------------------------------------


def sdk_available() -> bool:
    """Whether the sdk *surface* is importable here — not merely the package name.

    A stale editable install can leave `libs/sdk/src/sdk` behind as an empty
    namespace package, so `import sdk` succeeds on a checkout that has no sdk at
    all. Probe the symbols the arm actually measures; the package name is a
    location, not a capability.
    """
    try:
        from sdk import emit_fact, read_facts, read_summary, search_facts  # noqa: F401
    except ImportError:
        return False
    return True


def run_arm(
    depths: tuple[int, ...], label: str | None, record: Path | None = None
) -> dict[str, Any]:
    """Measure every layer across the depth sweep, returning one recordable arm.

    A deep sweep is dominated by fill time and runs for tens of minutes. The arm
    is flushed to `record` after every depth, so a failure in the 100k band still
    leaves the 1k and 10k bands on disk — the depths already measured are the
    part of the curve you can still trust.
    """
    include_sdk = sdk_available()
    samples: list[Sample] = []
    environment = capture_environment()

    print(
        f"Instrument v{INSTRUMENT_VERSION} · depths {list(depths)} · "
        f"sdk={'yes' if include_sdk else 'ABSENT'} · {environment['git_describe']}"
    )

    def arm(completed: list[int]) -> dict[str, Any]:
        return {
            "instrument_version": INSTRUMENT_VERSION,
            "label": label or (environment["git_branch"] or "unlabelled"),
            "sdk_present": include_sdk,
            "depths": completed,
            "environment": environment,
            "samples": [asdict(s) for s in samples],
        }

    def flush(completed: list[int]) -> None:
        if record is not None:
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text(json.dumps(arm(completed), indent=2) + "\n")

    print("  cli cold start ...", flush=True)
    samples.extend(probe_cli())

    completed: list[int] = []
    for depth in depths:
        started = time.perf_counter()
        print(f"  store layer @ depth {depth:,} ...", flush=True)
        samples.extend(probe_store(depth))
        print(f"  engine{'+sdk' if include_sdk else ''} layers @ depth {depth:,} ...", flush=True)
        samples.extend(probe_vertex_layers(depth, include_sdk))
        completed.append(depth)
        flush(completed)
        print(f"    depth {depth:,} done in {time.perf_counter() - started:.1f}s", flush=True)

    return arm(completed)


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def _samples_of(arm: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f"{s['probe']}@{s['depth']}": s for s in arm["samples"]}


def render_curves(arm: dict[str, Any]) -> str:
    """Per-probe cost across the depth sweep, with the growth factor made explicit."""
    by_probe: dict[str, list[dict[str, Any]]] = {}
    for sample in arm["samples"]:
        by_probe.setdefault(sample["probe"], []).append(sample)

    depths = arm["depths"]
    lines = []
    header = "| Probe | Layer | " + " | ".join(f"n={d:,}" for d in depths) + " | growth |"
    lines.append(header)
    lines.append("| :--- | :--- | " + " | ".join("---:" for _ in depths) + " | ---: |")

    for probe, entries in by_probe.items():
        entries.sort(key=lambda s: s["depth"])
        if len(entries) == 1 and entries[0]["depth"] == 0:
            cells = [f"{entries[0]['median']:.3f}"] + ["—"] * (len(depths) - 1)
            lines.append(f"| `{probe}` | {entries[0]['layer']} | " + " | ".join(cells) + " | n/a |")
            continue

        at_depth = {e["depth"]: e for e in entries}
        cells = []
        for depth in depths:
            entry = at_depth.get(depth)
            cells.append(f"{entry['median']:.3f}" if entry else "—")

        first = at_depth.get(depths[0])
        last = at_depth.get(depths[-1])
        if first and last and first["median"] > 0:
            growth = f"{last['median'] / first['median']:.1f}x"
        else:
            growth = "—"
        lines.append(
            f"| `{probe}` | {entries[0]['layer']} | " + " | ".join(cells) + f" | {growth} |"
        )

    return "\n".join(lines)


def compare_arms(
    reference: dict[str, Any],
    candidate: dict[str, Any],
    bracket: dict[str, Any] | None,
) -> tuple[str, list[str]]:
    """Compare two arms, resolving deltas only above the session's measured noise.

    Without a bracket the comparison still prints, but every delta is reported as
    UNRESOLVED — the instrument has no evidence about its own noise floor, so it
    is not entitled to call anything a change.
    """
    warnings: list[str] = []

    if reference["instrument_version"] != candidate["instrument_version"]:
        raise SystemExit(
            f"refusing to compare: instrument v{reference['instrument_version']} vs "
            f"v{candidate['instrument_version']} — probes do not mean the same thing"
        )

    ref_env, cand_env = reference["environment"], candidate["environment"]
    for field in ("hostname", "cpu", "python"):
        if ref_env.get(field) != cand_env.get(field):
            warnings.append(
                f"{field} differs between arms ({ref_env.get(field)!r} vs {cand_env.get(field)!r}) "
                f"— absolute comparison across machines is not meaningful"
            )
    if "unknown" in (ref_env.get("power_source"), cand_env.get("power_source")):
        warnings.append("power source unknown for at least one arm — thermal state unverified")

    ref_samples = _samples_of(reference)
    cand_samples = _samples_of(candidate)

    noise: dict[str, float] = {}
    if bracket is not None:
        for key, repeat in _samples_of(bracket).items():
            original = ref_samples.get(key)
            if original and original["median"] > 0:
                noise[key] = abs(repeat["median"] - original["median"]) / original["median"] * 100.0
    else:
        warnings.append(
            "no --bracket arm supplied — the session noise floor is unmeasured, so every "
            "delta below is UNRESOLVED regardless of size"
        )

    lines = [
        "| Probe @ depth | Reference | Candidate | Delta | Noise floor | Verdict |",
        "| :--- | ---: | ---: | ---: | ---: | :--- |",
    ]
    for key, ref in sorted(ref_samples.items()):
        cand = cand_samples.get(key)
        if cand is None:
            continue
        if ref["median"] == 0:
            continue
        delta = (cand["median"] - ref["median"]) / ref["median"] * 100.0
        floor = noise.get(key)
        if floor is None:
            verdict = "UNRESOLVED"
            floor_cell = "unmeasured"
        else:
            floor_cell = f"±{floor:.1f}%"
            verdict = "resolved" if abs(delta) > max(floor, 1.0) else "within noise"
        lines.append(
            f"| `{key}` | {ref['median']:.3f} | {cand['median']:.3f} | "
            f"{delta:+.1f}% | {floor_cell} | {verdict} |"
        )

    # Probes present in only one arm are information, not omissions.
    only_candidate = sorted(set(cand_samples) - set(ref_samples))
    if only_candidate:
        lines.append("")
        lines.append(f"Present only in candidate ({len(only_candidate)}): " + ", ".join(f"`{k}`" for k in only_candidate))

    return "\n".join(lines), warnings


def _load(path: str) -> dict[str, Any]:
    with open(path) as handle:
        return json.load(handle)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Characterization ledger for the loops core — scaling curves, not a PR gate."
    )
    parser.add_argument("--record", help="write the measured arm to this JSON path")
    parser.add_argument("--label", help="name for this arm (defaults to the git branch)")
    parser.add_argument(
        "--depths",
        default=",".join(str(d) for d in DEFAULT_DEPTHS),
        help=f"comma-separated store depths to sweep (default: {','.join(str(d) for d in DEFAULT_DEPTHS)})",
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("REFERENCE", "CANDIDATE"),
        help="compare two recorded arms instead of measuring",
    )
    parser.add_argument(
        "--bracket",
        metavar="REFERENCE_REPEAT",
        help="a second measurement of the reference arm; establishes the session noise floor",
    )
    args = parser.parse_args()

    if args.compare:
        reference, candidate = (_load(p) for p in args.compare)
        bracket = _load(args.bracket) if args.bracket else None
        report, warnings = compare_arms(reference, candidate, bracket)
        print(f"=== {reference['label']} → {candidate['label']} ===\n")
        print(report)
        if warnings:
            print("\nCaveats:")
            for warning in warnings:
                print(f"  ! {warning}")
        return

    if shutil.which("uv") is None:
        raise SystemExit("uv not found on PATH — the cli probe needs it")

    depths = tuple(int(d.strip()) for d in args.depths.split(",") if d.strip())
    record = Path(args.record) if args.record else None
    arm = run_arm(depths, args.label, record)

    print(f"\n=== Cost curves: {arm['label']} ===\n")
    print(render_curves(arm))

    if record is not None:
        print(f"\nRecorded arm → {record}")


if __name__ == "__main__":
    main()

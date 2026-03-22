"""Test builders for loops app tests.

Provides composable, fluent builders for test data. Three layers:

  atoms layer  — FoldStateBuilder (FoldState / FoldSection / FoldItem trees)
  tui layer    — IterationBuilder, AppStateBuilder, StoreExplorerStateBuilder
  store layer  — StorePopulator (emit Fact objects into a SqliteStore)

Designed to be imported directly from any test file without pytest setup:

    from .builders import FoldStateBuilder, AppStateBuilder, StorePopulator

For pytest fixtures that compose these builders with tmp_path, see conftest.py.

Engine vertex construction uses the existing engine.builder SDK:

    from engine.builder import vertex, fold_by, fold_count, fold_collect
"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atoms import Fact, FoldItem, FoldSection, FoldState
from painted.views import DataExplorerState, ListState


# ---------------------------------------------------------------------------
# FoldState builder
# ---------------------------------------------------------------------------

class FoldStateBuilder:
    """Fluent builder for FoldState / FoldSection / FoldItem trees.

    Usage::

        fs = (FoldStateBuilder("my-vertex")
            .config(primary_metric="efficiency", direction="lower")
            .experiment(efficiency=4.5, status="keep", commit="abc1234",
                        description="baseline", ts=200.0)
            .experiment(efficiency=3.5, status="keep", commit="def5678",
                        description="step up", ts=300.0)
            .log(type="note", message="mid experiment", ts=250.0)
            .build())
    """

    def __init__(self, vertex: str = "test") -> None:
        self._vertex = vertex
        self._sections: dict[str, list[FoldItem]] = {}

    def _item(self, kind: str, payload: dict, ts: float | None = None) -> "FoldStateBuilder":
        self._sections.setdefault(kind, [])
        self._sections[kind].append(FoldItem(payload=payload, ts=ts or time.time()))
        return self

    def config(self, **kv: str) -> "FoldStateBuilder":
        """Add config key/value entries (used by autoresearch TUI for primary_metric, direction)."""
        for key, value in kv.items():
            self._item("config", {"key": key, "value": value}, ts=100.0)
        return self

    def experiment(self, *, ts: float | None = None, **payload) -> "FoldStateBuilder":
        """Add an experiment fact. Keyword args become the payload."""
        # Coerce numeric values to strings so payload matches the on-disk format
        str_payload = {k: str(v) for k, v in payload.items()}
        return self._item("experiment", str_payload, ts=ts)

    def log(self, *, ts: float | None = None, **payload) -> "FoldStateBuilder":
        return self._item("log", payload, ts=ts)

    def finding(self, *, ts: float | None = None, **payload) -> "FoldStateBuilder":
        return self._item("finding", payload, ts=ts)

    def idea(self, *, ts: float | None = None, **payload) -> "FoldStateBuilder":
        return self._item("idea", payload, ts=ts)

    def hypothesis(self, *, ts: float | None = None, **payload) -> "FoldStateBuilder":
        return self._item("hypothesis", payload, ts=ts)

    def section(self, kind: str, *, ts: float | None = None, **payload) -> "FoldStateBuilder":
        """Add a raw fact to an arbitrary section kind."""
        return self._item(kind, payload, ts=ts)

    def build(self) -> FoldState:
        sections = tuple(
            FoldSection(kind=kind, items=tuple(items))
            for kind, items in self._sections.items()
        )
        return FoldState(sections=sections, vertex=self._vertex)


# ---------------------------------------------------------------------------
# IterationView / AppState builders
# ---------------------------------------------------------------------------

def make_iteration(
    number: int = 1,
    *,
    status: str = "keep",
    metric: float | None = 3.5,
    delta_pct: float | None = None,
    is_running: bool = False,
    commit: str = "abc1234",
    description: str = "test step",
    logs: tuple = (),
    findings: tuple = (),
    ideas: tuple = (),
    hypotheses: tuple = (),
) -> Any:  # IterationView — imported lazily to avoid circular import at module level
    """Build a single IterationView for AutoresearchApp tests."""
    from loops.tui.autoresearch_app import IterationView
    return IterationView(
        number=number,
        is_running=is_running,
        commit=commit,
        metric=metric,
        status=status,
        delta_pct=delta_pct,
        description=description,
        logs=logs,
        findings=findings,
        ideas=ideas,
        hypotheses=hypotheses,
    )


class AppStateBuilder:
    """Build an AppState for AutoresearchApp tests.

    Usage::

        state = (AppStateBuilder()
            .metric("efficiency", direction="lower")
            .iteration(metric=4.5, status="keep")
            .iteration(metric=3.5, status="keep", delta_pct=-22.2)
            .running()  # add an in-progress iteration
            .focus("list")
            .build())
    """

    def __init__(self) -> None:
        self._primary_metric = "efficiency"
        self._direction = "lower"
        self._iterations: list[Any] = []
        self._focus = "list"
        self._detail_scroll = 0

    def metric(self, name: str, *, direction: str = "lower") -> "AppStateBuilder":
        self._primary_metric = name
        self._direction = direction
        return self

    def iteration(self, **kwargs) -> "AppStateBuilder":
        n = len(self._iterations) + 1
        self._iterations.append(make_iteration(number=n, **kwargs))
        return self

    def running(self, **kwargs) -> "AppStateBuilder":
        n = len(self._iterations) + 1
        self._iterations.append(make_iteration(number=n, is_running=True, metric=None, **kwargs))
        return self

    def focus(self, panel: str) -> "AppStateBuilder":
        self._focus = panel
        return self

    def scroll(self, offset: int) -> "AppStateBuilder":
        self._detail_scroll = offset
        return self

    def build(self) -> Any:  # AppState
        from loops.tui.autoresearch_app import AppState

        metrics = [it.metric for it in self._iterations if it.metric is not None and not it.is_running]
        baseline = metrics[0] if metrics else None
        if self._direction == "lower":
            best = min(metrics) if metrics else None
        else:
            best = max(metrics) if metrics else None
        best_run = next(
            (it.number for it in self._iterations if it.metric == best), 0
        )

        return AppState(
            config={"primary_metric": self._primary_metric, "direction": self._direction},
            iterations=self._iterations,
            primary_metric=self._primary_metric,
            direction=self._direction,
            baseline=baseline,
            best=best,
            best_run=best_run,
            total_experiments=len([it for it in self._iterations if not it.is_running]),
            cursor=ListState().with_count(len(self._iterations)),
            focus=self._focus,
            detail_scroll=self._detail_scroll,
        )

    @staticmethod
    def from_fold(fold_state: FoldState) -> Any:
        """Delegate to AppState.from_fold — convenience for round-trip tests."""
        from loops.tui.autoresearch_app import AppState
        return AppState.from_fold(fold_state)


# ---------------------------------------------------------------------------
# StoreExplorerState builder
# ---------------------------------------------------------------------------

def make_store_summary(
    *,
    tick_names: list[str] | None = None,
    facts_total: int = 10,
    kinds: dict[str, int] | None = None,
    freshness: datetime | None = None,
) -> dict:
    """Build a summary dict compatible with StoreExplorerState.from_summary.

    The summary format mirrors what make_fetcher() returns from the store command.
    """
    tick_names = tick_names or ["2024-01-01", "2024-01-02"]
    kinds = kinds or {"thread": 5, "decision": 5}
    freshness = freshness or datetime(2024, 1, 2, 12, 0, 0, tzinfo=timezone.utc)

    names: dict[str, dict] = {}
    for i, name in enumerate(tick_names):
        since_ts = 1704067200.0 + i * 86400.0
        until_ts = since_ts + 86400.0
        latest = datetime.fromtimestamp(until_ts - 3600, tz=timezone.utc)
        names[name] = {
            "count": max(1, facts_total // len(tick_names)),
            "sparkline": "▃▄▅"[: i + 1],
            "latest": latest,
            "since": since_ts,
            "until": until_ts,
        }

    return {
        "facts": {"total": facts_total, "kinds": kinds},
        "ticks": {"total": len(tick_names), "names": names},
        "freshness": freshness,
    }


class StoreExplorerStateBuilder:
    """Build a StoreExplorerState for StoreExplorerApp tests.

    Usage::

        state = (StoreExplorerStateBuilder()
            .ticks(["2024-01-01", "2024-01-02"])
            .with_detail()   # populate detail for first tick
            .focus("list")
            .build())
    """

    def __init__(self) -> None:
        self._tick_names: list[str] = ["2024-01-01", "2024-01-02"]
        self._facts_total = 10
        self._kinds: dict[str, int] = {"thread": 5, "decision": 5}
        self._with_detail = False
        self._fidelity_facts: list[dict] | None = None
        self._focus = "list"

    def ticks(self, names: list[str]) -> "StoreExplorerStateBuilder":
        self._tick_names = names
        return self

    def facts(self, total: int, **kinds: int) -> "StoreExplorerStateBuilder":
        self._facts_total = total
        if kinds:
            self._kinds = dict(kinds)
        return self

    def with_detail(self) -> "StoreExplorerStateBuilder":
        self._with_detail = True
        return self

    def with_fidelity(self, facts: list[dict]) -> "StoreExplorerStateBuilder":
        self._fidelity_facts = facts
        return self

    def focus(self, panel: str) -> "StoreExplorerStateBuilder":
        self._focus = panel
        return self

    def build(self) -> Any:  # StoreExplorerState
        from loops.tui.store_app import StoreExplorerState, FidelityState

        summary = make_store_summary(
            tick_names=self._tick_names,
            facts_total=self._facts_total,
            kinds=self._kinds,
        )
        state = StoreExplorerState.from_summary(summary)
        state = replace(state, focus=self._focus)

        if self._with_detail:
            first_tick = self._tick_names[0] if self._tick_names else None
            if first_tick:
                tick_data = summary["ticks"]["names"].get(first_tick, {})
                state = replace(state, detail=DataExplorerState(data=tick_data))

        if self._fidelity_facts is not None:
            first_name = self._tick_names[0] if self._tick_names else "tick"
            tick_info = summary["ticks"]["names"].get(first_name, {})
            fid = FidelityState(
                facts=self._fidelity_facts,
                tick_name=first_name,
                since=tick_info.get("since", 0.0),
                until=tick_info.get("until", 1.0),
                cursor=ListState().with_count(len(self._fidelity_facts)),
            )
            state = replace(state, fidelity=fid)

        return state


# ---------------------------------------------------------------------------
# Fidelity facts builder
# ---------------------------------------------------------------------------

def make_fidelity_facts(
    kinds: list[str] | None = None,
    *,
    observer: str = "test",
    base_ts: datetime | None = None,
) -> list[dict]:
    """Build a list of raw fact dicts suitable for FidelityState.facts."""
    kinds = kinds or ["thread", "decision"]
    base_ts = base_ts or datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    facts = []
    for i, kind in enumerate(kinds):
        ts = datetime.fromtimestamp(base_ts.timestamp() + i * 3600, tz=timezone.utc)
        payload: dict[str, Any] = {"kind_index": str(i)}
        if kind == "thread":
            payload = {"name": f"thread-{i}", "status": "open"}
        elif kind == "decision":
            payload = {"topic": f"decision-{i}", "message": "chose x"}
        facts.append({"kind": kind, "observer": observer, "ts": ts, "payload": payload})
    return facts


# ---------------------------------------------------------------------------
# Store populator
# ---------------------------------------------------------------------------

class StorePopulator:
    """Populate a SqliteStore with Fact objects for test setup.

    Usage::

        db_path = tmp_path / "test.db"
        StorePopulator(db_path).emit("thread", name="foo", status="open").emit("thread", name="bar").done()
    """

    def __init__(self, db_path: Path, *, observer: str = "test") -> None:
        self._path = db_path
        self._observer = observer
        self._facts: list[Fact] = []

    def emit(self, kind: str, *, ts: float | None = None, **payload) -> "StorePopulator":
        self._facts.append(Fact(
            kind=kind,
            payload=payload,
            ts=ts or time.time(),
            observer=self._observer,
            origin="test",
        ))
        return self

    def done(self) -> Path:
        """Write all queued facts to the store and return the db path."""
        from engine import SqliteStore
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with SqliteStore(
            path=self._path,
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        ) as store:
            for fact in self._facts:
                store.append(fact)
        return self._path

    def facts(self) -> list[Fact]:
        """Return queued facts without writing (for inspection before done())."""
        return list(self._facts)

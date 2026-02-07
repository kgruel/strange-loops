"""Store explorer TUI — interactive inspection of loops store contents."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from pathlib import Path

from cells import Block, Style, join_horizontal, join_vertical, pad, border, ROUNDED
from cells.components.data_explorer import DataExplorerState, data_explorer
from cells.components.list_view import ListState, list_view
from cells.lens import shape_lens
from cells.span import Line, Span
from cells.tui import Surface


@dataclass(frozen=True)
class FidelityState:
    """Immutable state for the fidelity drill view."""

    facts: list[dict]
    tick_name: str
    since: float
    until: float
    cursor: ListState
    filtered: bool = False
    filter_kind: str | None = None


@dataclass(frozen=True)
class StoreExplorerState:
    """Immutable state for the store explorer."""

    summary: dict
    kinds: list[str]
    tick_names: list[str]
    cursor: ListState
    detail: DataExplorerState | None = None
    focus: str = "list"  # "list", "detail", or "fidelity"
    fidelity: FidelityState | None = None

    @staticmethod
    def from_summary(summary: dict) -> StoreExplorerState:
        """Build initial state from a store summary."""
        fact_kinds = list(summary.get("facts", {}).get("kinds", {}).keys())
        tick_names = list(summary.get("ticks", {}).get("names", {}).keys())
        all_items = [f"[fact] {k}" for k in fact_kinds] + [f"[tick] {n}" for n in tick_names]
        return StoreExplorerState(
            summary=summary,
            kinds=fact_kinds,
            tick_names=tick_names,
            cursor=ListState(item_count=len(all_items)),
        )

    @property
    def items(self) -> list[str]:
        """All navigable items (facts then ticks)."""
        return [f"[fact] {k}" for k in self.kinds] + [f"[tick] {n}" for n in self.tick_names]

    @property
    def selected_label(self) -> str | None:
        """Label of the currently selected item."""
        items = self.items
        if not items or self.cursor.selected >= len(items):
            return None
        return items[self.cursor.selected]

    def selected_is_tick(self) -> bool:
        """Whether the current selection is a tick item."""
        return self.cursor.selected >= len(self.kinds)

    def selected_tick_name(self) -> str | None:
        """Name of the currently selected tick, or None if a fact is selected."""
        idx = self.cursor.selected - len(self.kinds)
        if 0 <= idx < len(self.tick_names):
            return self.tick_names[idx]
        return None

    def selected_data(self) -> dict | None:
        """Data for the currently selected item."""
        idx = self.cursor.selected
        if idx < len(self.kinds):
            kind = self.kinds[idx]
            return self.summary["facts"]["kinds"].get(kind, {})
        tick_idx = idx - len(self.kinds)
        if tick_idx < len(self.tick_names):
            name = self.tick_names[tick_idx]
            return self.summary["ticks"]["names"].get(name, {})
        return None


class StoreExplorerApp(Surface):
    """Interactive store explorer TUI."""

    def __init__(self, store_path: Path) -> None:
        super().__init__(fps_cap=30, on_start=self._on_start)
        self._store_path = store_path
        self._state: StoreExplorerState | None = None
        self._fidelity_fetch = None  # set during _load_store
        self._error: str | None = None
        self._w = 80
        self._h = 24

    def layout(self, width: int, height: int) -> None:
        self._w = width
        self._h = height

    async def _on_start(self) -> None:
        """Load store data on startup."""
        asyncio.get_running_loop().call_soon(self._load_store)

    def _load_store(self) -> None:
        """Synchronous store load."""
        try:
            from loops.commands.store import make_fetcher, make_fidelity_fetcher

            fetch = make_fetcher(self._store_path, zoom=2)
            data = fetch()
            self._fidelity_fetch = make_fidelity_fetcher(self._store_path)
            self._state = StoreExplorerState.from_summary(data)
            # Initialize detail for first item
            sel_data = self._state.selected_data()
            if sel_data:
                self._state = replace(
                    self._state,
                    detail=DataExplorerState(data=sel_data),
                )
        except Exception as e:
            self._error = str(e)
        self.mark_dirty()

    def on_key(self, key: str) -> None:
        if key in ("q", "Q", "escape"):
            self.quit()
            return

        if self._state is None:
            return

        state = self._state

        if state.fidelity is not None:
            self._handle_fidelity_key(key)
            return

        if key == "tab":
            new_focus = "detail" if state.focus == "list" else "list"
            self._state = replace(state, focus=new_focus)
            self.mark_dirty()
            return

        if key == "f" and state.selected_is_tick():
            self._drill_fidelity()
            return

        if state.focus == "list":
            self._handle_list_key(key)
        elif state.focus == "detail" and state.detail is not None:
            self._handle_detail_key(key)

    def _handle_list_key(self, key: str) -> None:
        state = self._state
        if state is None:
            return

        old_selected = state.cursor.selected

        if key in ("j", "down"):
            new_cursor = state.cursor.move_down()
        elif key in ("k", "up"):
            new_cursor = state.cursor.move_up()
        elif key in ("g", "home"):
            new_cursor = state.cursor.move_to(0)
        elif key in ("G", "end"):
            new_cursor = state.cursor.move_to(state.cursor.item_count - 1)
        else:
            return

        new_state = replace(state, cursor=new_cursor)

        # Update detail if selection changed
        if new_cursor.selected != old_selected:
            sel_data = new_state.selected_data()
            if sel_data:
                new_state = replace(
                    new_state,
                    detail=DataExplorerState(data=sel_data),
                )
            else:
                new_state = replace(new_state, detail=None)

        self._state = new_state
        self.mark_dirty()

    def _handle_detail_key(self, key: str) -> None:
        state = self._state
        if state is None or state.detail is None:
            return

        detail = state.detail
        if key in ("j", "down"):
            detail = detail.move_down()
        elif key in ("k", "up"):
            detail = detail.move_up()
        elif key in ("enter", " "):
            detail = detail.toggle_expand()
        elif key in ("g", "home"):
            detail = detail.home()
        elif key in ("G", "end"):
            detail = detail.end()
        elif key == "pageup":
            detail = detail.page_up()
        elif key == "pagedown":
            detail = detail.page_down()
        else:
            return

        self._state = replace(state, detail=detail)
        self.mark_dirty()

    def _drill_fidelity(self) -> None:
        """Enter fidelity drill for the currently selected tick."""
        state = self._state
        if state is None or self._fidelity_fetch is None:
            return

        tick_name = state.selected_tick_name()
        if tick_name is None:
            return

        tick_info = state.summary["ticks"]["names"].get(tick_name, {})
        since_ts = tick_info.get("latest_since")
        until_ts = tick_info.get("latest_ts")
        if since_ts is None or until_ts is None:
            return

        facts = self._fidelity_fetch(since_ts, until_ts)
        self._state = replace(
            state,
            focus="fidelity",
            fidelity=FidelityState(
                facts=facts,
                tick_name=tick_name,
                since=since_ts,
                until=until_ts,
                cursor=ListState(item_count=len(facts)),
            ),
        )
        self.mark_dirty()

    def _handle_fidelity_key(self, key: str) -> None:
        state = self._state
        if state is None or state.fidelity is None:
            return

        fid = state.fidelity

        if key == "backspace":
            self._state = replace(state, focus="list", fidelity=None)
            self.mark_dirty()
            return

        if key == "a" and self._fidelity_fetch is not None:
            if not fid.filtered:
                # Switch to filtered: pick the kind at cursor
                if fid.facts and 0 <= fid.cursor.selected < len(fid.facts):
                    kind = fid.facts[fid.cursor.selected]["kind"]
                elif fid.facts:
                    kind = fid.facts[0]["kind"]
                else:
                    return
                filtered = self._fidelity_fetch(fid.since, fid.until, kind=kind)
                self._state = replace(
                    state,
                    fidelity=replace(
                        fid,
                        facts=filtered,
                        filtered=True,
                        filter_kind=kind,
                        cursor=ListState(item_count=len(filtered)),
                    ),
                )
            else:
                # Switch back to all kinds
                all_facts = self._fidelity_fetch(fid.since, fid.until)
                self._state = replace(
                    state,
                    fidelity=replace(
                        fid,
                        facts=all_facts,
                        filtered=False,
                        filter_kind=None,
                        cursor=ListState(item_count=len(all_facts)),
                    ),
                )
            self.mark_dirty()
            return

        cursor = fid.cursor
        if key in ("j", "down"):
            cursor = cursor.move_down()
        elif key in ("k", "up"):
            cursor = cursor.move_up()
        elif key in ("g", "home"):
            cursor = cursor.move_to(0)
        elif key in ("G", "end"):
            cursor = cursor.move_to(cursor.item_count - 1)
        else:
            return

        self._state = replace(state, fidelity=replace(fid, cursor=cursor))
        self.mark_dirty()

    def _render_fidelity_panel(
        self, fid: FidelityState, width: int, height: int,
    ) -> Block:
        """Render the fidelity drill as a bordered panel."""
        from datetime import datetime, timezone

        inner_w = width - 4  # border eats 2 per side
        inner_h = height - 2

        since_str = datetime.fromtimestamp(fid.since, tz=timezone.utc).strftime("%H:%M:%S")
        until_str = datetime.fromtimestamp(fid.until, tz=timezone.utc).strftime("%H:%M:%S")

        if fid.filtered and fid.filter_kind:
            filter_tag = fid.filter_kind
        else:
            distinct = len({f["kind"] for f in fid.facts})
            filter_tag = f"all {distinct} kinds"

        title = (
            f"Fidelity: {fid.tick_name} "
            f"[{since_str}\u2192{until_str}] "
            f"({len(fid.facts)} facts, {filter_tag})"
        )

        # Render fact rows
        scroll_state = fid.cursor.scroll_into_view(inner_h)
        rows: list[Block] = []
        visible_start = scroll_state.scroll_offset
        visible_end = visible_start + inner_h

        for i in range(visible_start, min(visible_end, len(fid.facts))):
            fact = fid.facts[i]
            ts = fact["ts"].strftime("%H:%M:%S") if hasattr(fact["ts"], "strftime") else "?"
            kind = fact.get("kind", "?")
            obs = fact.get("observer", "?")
            payload_preview = _payload_one_liner(fact.get("payload"), inner_w - 30)
            line = f"{ts} {kind:>12} {obs:>8} {payload_preview}"
            if len(line) > inner_w:
                line = line[: inner_w - 1] + "\u2026"
            line = line.ljust(inner_w)

            is_selected = i == fid.cursor.selected
            style = Style(reverse=True) if is_selected else Style()
            rows.append(Block.text(line, style, width=inner_w))

        if not rows:
            rows.append(Block.text("(no facts in period)", Style(dim=True), width=inner_w))

        while len(rows) < inner_h:
            rows.append(Block.empty(inner_w, 1))

        inner = join_vertical(*rows[:inner_h])
        return border(inner, title=title, style=Style(bold=True), chars=ROUNDED)

    def render(self) -> None:
        if self._buf is None:
            return

        width = self._buf.width
        height = self._buf.height

        if self._error:
            block = Block.text(f"Error: {self._error}", Style(), width=width)
            self._buf.fill(0, 0, width, height, " ", Style())
            block.paint(self._buf.region(0, 0, width, 1), 0, 0)
            return

        if self._state is None:
            block = Block.text("Loading...", Style(dim=True), width=width)
            self._buf.fill(0, 0, width, height, " ", Style())
            block.paint(self._buf.region(0, 0, width, 1), 0, 0)
            return

        state = self._state

        # Header
        facts_total = state.summary["facts"]["total"]
        ticks_total = state.summary["ticks"]["total"]
        header_text = f"Store: {facts_total} facts, {ticks_total} ticks"
        header = Block.text(header_text, Style(bold=True), width=width)

        # Footer / help
        if state.fidelity is not None:
            filter_label = "all" if state.fidelity.filtered else "filter"
            help_text = f"[j/k] navigate  [a] {filter_label}  [bksp] back  [q]uit"
        else:
            tick_hint = "  [f] fidelity" if state.selected_is_tick() else ""
            focus_hint = "list" if state.focus == "list" else "detail"
            help_text = f"[j/k] navigate  [tab] switch ({focus_hint}){tick_hint}  [enter] expand  [q]uit"
        footer = Block.text(help_text, Style(dim=True), width=width)

        # Panel dimensions
        panel_height = max(5, height - 4)  # header + gap + footer + gap
        left_width = max(20, min(width // 3, 40))
        right_width = max(10, width - left_width - 3)  # 3 for gap

        # Left panel: kind/tick list
        items = state.items
        lines = [Line(spans=(Span(item, Style()),)) for item in items]
        scroll_state = state.cursor.scroll_into_view(panel_height - 2)
        list_block = list_view(scroll_state, lines, panel_height - 2)
        left_style = Style(bold=True) if state.focus == "list" else Style(dim=True)
        left_panel = border(list_block, title="Kinds", style=left_style, chars=ROUNDED)

        # Right panel: detail explorer or fidelity drill
        if state.fidelity is not None:
            right_panel = self._render_fidelity_panel(
                state.fidelity, right_width, panel_height,
            )
        elif state.detail is not None:
            detail_state = state.detail.with_visible(panel_height - 2)
            detail_block = data_explorer(detail_state, right_width - 4, panel_height - 2)
            right_style = Style(bold=True) if state.focus == "detail" else Style(dim=True)
            right_title = state.selected_label or "Detail"
            right_panel = border(detail_block, title=right_title, style=right_style, chars=ROUNDED)
        else:
            detail_block = Block.text("(no selection)", Style(dim=True), width=right_width - 4)
            right_panel = border(detail_block, title="Detail", style=Style(dim=True), chars=ROUNDED)

        # Compose
        gap = Block.empty(1, panel_height)
        panels = join_horizontal(left_panel, gap, right_panel)

        body = join_vertical(
            header,
            Block.empty(width, 1),
            panels,
            Block.empty(width, 1),
            footer,
        )

        padded = pad(body, left=1, top=0)

        # Paint
        self._buf.fill(0, 0, width, height, " ", Style())
        region = self._buf.region(0, 0, min(padded.width, width), min(padded.height, height))
        padded.paint(region, 0, 0)


def _payload_one_liner(payload, max_width: int) -> str:
    """Compress a payload into a short one-line preview."""
    if isinstance(payload, dict):
        parts = []
        for k, v in payload.items():
            if isinstance(v, str) and len(v) > 15:
                v = v[:12] + "\u2026"
            parts.append(f"{k}={v}")
        line = " ".join(parts)
    elif isinstance(payload, list):
        line = f"[{len(payload)} items]"
    else:
        line = str(payload) if payload is not None else ""

    if len(line) > max_width:
        line = line[: max_width - 1] + "\u2026"
    return line

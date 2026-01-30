"""Command with flags that becomes a TUI at high fidelity.

Demonstrates Concept 2: CLI flags → TUI form progression:
- Level 0 (-q): Silent, exit code only
- Level 1 (default): Parse flags, run, print result
- Level 2 (-v): Show styled progress steps
- Level 3 (-vv): Interactive TUI to fill fields

Run:
    uv run python experiments/fidelity/deploy_demo.py api           # Level 1
    uv run python experiments/fidelity/deploy_demo.py -q api        # Level 0
    uv run python experiments/fidelity/deploy_demo.py -v api        # Level 2
    uv run python experiments/fidelity/deploy_demo.py -vv           # Level 3 (TUI)
"""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass, replace

from cells import (
    Block,
    Style,
    border,
    join_vertical,
    join_horizontal,
    ROUNDED,
    print_block,
)
from cells.tui import Surface
from cells.widgets import ListState

from .common import Fidelity, parse_fidelity, is_interactive, terminal_width


@dataclass(frozen=True)
class DeployConfig:
    """Configuration for a deployment."""

    service: str | None = None
    env: str = "staging"
    replicas: int = 1
    dry_run: bool = False


@dataclass(frozen=True)
class DeployContext:
    """Available options from the system."""

    environments: tuple[str, ...]
    services: tuple[str, ...]


# Sample context
SAMPLE_CONTEXT = DeployContext(
    environments=("dev", "staging", "prod"),
    services=("api", "web", "worker", "scheduler"),
)


def parse_config(args: list[str]) -> DeployConfig:
    """Parse deployment config from args (simplified argparse)."""
    config = DeployConfig()
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-e", "--env") and i + 1 < len(args):
            config = replace(config, env=args[i + 1])
            i += 2
        elif arg in ("-r", "--replicas") and i + 1 < len(args):
            config = replace(config, replicas=int(args[i + 1]))
            i += 2
        elif arg in ("-d", "--dry-run"):
            config = replace(config, dry_run=True)
            i += 1
        elif not arg.startswith("-"):
            config = replace(config, service=arg)
            i += 1
        else:
            i += 1  # skip fidelity flags, etc.
    return config


def deploy_minimal(config: DeployConfig) -> int:
    """Level 0: Minimal execution."""
    if not config.service:
        return 1
    # Simulate deployment (would actually do work here)
    return 0


def deploy_standard(config: DeployConfig) -> int:
    """Level 1: Standard output."""
    if not config.service:
        print("Error: service required")
        return 1

    action = "Would deploy" if config.dry_run else "Deployed"
    print(f"{action} {config.service} to {config.env} ({config.replicas} replicas)")
    return 0


def deploy_styled(config: DeployConfig, width: int) -> int:
    """Level 2: Styled progress output."""
    if not config.service:
        error = Block.text("Error: service required", Style(fg="red", bold=True))
        print_block(error)
        return 1

    # Config panel
    config_lines = [
        Block.text(f"Service:     {config.service}", Style()),
        Block.text(f"Environment: {config.env}", Style()),
        Block.text(f"Replicas:    {config.replicas}", Style()),
    ]
    if config.dry_run:
        config_lines.append(Block.text("Mode:        dry-run", Style(fg="yellow")))

    config_block = join_vertical(*config_lines)
    config_box = border(config_block, title="Deploy", chars=ROUNDED)
    print_block(config_box)

    # Progress steps
    steps = [
        ("Validating config", 0.2),
        ("Building image", 0.5),
        ("Rolling out", 0.3),
    ]

    for i, (step_name, delay) in enumerate(steps):
        step_num = f"[{i+1}/{len(steps)}]"

        # In-progress state
        in_progress = Block.text(
            f"{step_num} {step_name}...",
            Style(fg="yellow"),
        )
        print_block(in_progress)

        if not config.dry_run:
            time.sleep(delay)  # Simulate work

        # Would overwrite line in real impl, here we just print done
        done = Block.text(
            f"{step_num} {step_name}... done",
            Style(fg="green"),
        )
        # Note: In a real impl, we'd use cursor movement to update in place

    # Result
    if config.dry_run:
        result = Block.text("Dry run complete", Style(fg="cyan", bold=True))
    else:
        result = Block.text("Deployed successfully", Style(fg="green", bold=True))
    print_block(result)

    return 0


class DeploySurface(Surface):
    """Level 3: Interactive TUI for deployment configuration."""

    FIELDS = ["service", "env", "replicas"]

    def __init__(self, context: DeployContext, initial: DeployConfig):
        super().__init__()
        self._context = context
        self._config = initial
        self._field_idx = 0  # Current field being edited
        self._cancelled = False
        self._confirmed = False

        # List states for selection fields
        self._service_list = ListState(
            selected=0,
            scroll_offset=0,
            item_count=len(context.services),
        )
        self._env_list = ListState(
            selected=context.environments.index(initial.env),
            scroll_offset=0,
            item_count=len(context.environments),
        )

        self._width = 80
        self._height = 24

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def final_config(self) -> DeployConfig:
        return self._config

    def layout(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def render(self) -> None:
        if self._buf is None:
            return

        self._buf.fill(0, 0, self._width, self._height, " ", Style())

        # Title
        title_style = Style(bold=True, fg="cyan", reverse=True)
        title_text = " Deploy Configuration ".center(self._width)
        title_block = Block.text(title_text, title_style)
        title_block.paint(self._buf, 0, 0)

        # Left column: form fields
        form_width = 30
        preview_width = self._width - form_width - 5

        # Service selector
        service_block = self._render_selector(
            "Service",
            self._context.services,
            self._service_list.selected,
            active=self._field_idx == 0,
            width=form_width - 2,
        )
        service_box = border(
            service_block,
            title="Service",
            chars=ROUNDED,
            style=Style(fg="cyan") if self._field_idx == 0 else Style(),
        )
        service_box.paint(self._buf, 0, 2)

        # Environment selector
        env_block = self._render_selector(
            "Environment",
            self._context.environments,
            self._env_list.selected,
            active=self._field_idx == 1,
            width=form_width - 2,
        )
        env_box = border(
            env_block,
            title="Environment",
            chars=ROUNDED,
            style=Style(fg="cyan") if self._field_idx == 1 else Style(),
        )
        env_box.paint(self._buf, 0, 6 + len(self._context.services))

        # Replicas counter
        replica_block = self._render_counter(
            self._config.replicas,
            active=self._field_idx == 2,
            width=form_width - 2,
        )
        replica_box = border(
            replica_block,
            title="Replicas",
            chars=ROUNDED,
            style=Style(fg="cyan") if self._field_idx == 2 else Style(),
        )
        replica_y = 10 + len(self._context.services) + len(self._context.environments)
        replica_box.paint(self._buf, 0, replica_y)

        # Right column: preview
        preview_block = self._render_preview(preview_width - 2)
        preview_box = border(preview_block, title="Preview", chars=ROUNDED)
        preview_box.paint(self._buf, form_width + 2, 2)

        # Footer
        footer_style = Style(dim=True)
        footer_text = " Tab: next field  j/k: select  Enter: deploy  Esc: cancel "
        footer_block = Block.text(footer_text, footer_style)
        footer_block.paint(self._buf, 0, self._height - 1)

    def _render_selector(
        self,
        label: str,
        items: tuple[str, ...],
        selected: int,
        active: bool,
        width: int,
    ) -> Block:
        """Render a selection list."""
        lines: list[Block] = []
        for i, item in enumerate(items):
            if i == selected:
                style = Style(bold=True, reverse=True) if active else Style(bold=True)
                prefix = "▸ " if active else "● "
            else:
                style = Style()
                prefix = "  "
            text = f"{prefix}{item}".ljust(width)
            lines.append(Block.text(text, style))
        return join_vertical(*lines)

    def _render_counter(self, value: int, active: bool, width: int) -> Block:
        """Render a numeric counter with arrows."""
        if active:
            style = Style(bold=True, fg="cyan")
            text = f"◀ {value} ▶"
        else:
            style = Style()
            text = f"  {value}  "
        return Block.text(text.center(width), style)

    def _render_preview(self, width: int) -> Block:
        """Render the deployment preview."""
        service = self._context.services[self._service_list.selected]
        env = self._context.environments[self._env_list.selected]
        replicas = self._config.replicas

        lines = [
            Block.text(f"Service:  {service}", Style(fg="green")),
            Block.text(f"Env:      {env}", Style(fg="yellow" if env == "prod" else "default")),
            Block.text(f"Replicas: {replicas}", Style()),
            Block.empty(width, 1),
        ]

        # Simulated diff
        lines.append(Block.text("Changes:", Style(bold=True)))
        lines.append(Block.text(f"  + scale to {replicas} replicas", Style(fg="green")))
        lines.append(Block.text(f"  ~ rolling update", Style(fg="yellow")))

        if env == "prod":
            lines.append(Block.empty(width, 1))
            lines.append(Block.text("⚠ Production deployment", Style(fg="red", bold=True)))

        return join_vertical(*lines)

    def on_key(self, key: str) -> None:
        if key == "escape":
            self._cancelled = True
            self.quit()
        elif key == "enter":
            self._confirmed = True
            self._finalize_config()
            self.quit()
        elif key == "tab":
            self._field_idx = (self._field_idx + 1) % len(self.FIELDS)
            self.mark_dirty()
        elif key in ("j", "down"):
            self._handle_down()
            self.mark_dirty()
        elif key in ("k", "up"):
            self._handle_up()
            self.mark_dirty()
        elif key in ("h", "left"):
            self._handle_left()
            self.mark_dirty()
        elif key in ("l", "right"):
            self._handle_right()
            self.mark_dirty()

    def _handle_down(self) -> None:
        if self._field_idx == 0:
            self._service_list = self._service_list.move_down()
        elif self._field_idx == 1:
            self._env_list = self._env_list.move_down()

    def _handle_up(self) -> None:
        if self._field_idx == 0:
            self._service_list = self._service_list.move_up()
        elif self._field_idx == 1:
            self._env_list = self._env_list.move_up()

    def _handle_left(self) -> None:
        if self._field_idx == 2:
            self._config = replace(self._config, replicas=max(1, self._config.replicas - 1))

    def _handle_right(self) -> None:
        if self._field_idx == 2:
            self._config = replace(self._config, replicas=min(10, self._config.replicas + 1))

    def _finalize_config(self) -> None:
        """Update config from current selections."""
        self._config = replace(
            self._config,
            service=self._context.services[self._service_list.selected],
            env=self._context.environments[self._env_list.selected],
        )


def deploy_interactive(context: DeployContext, initial: DeployConfig, width: int) -> int:
    """Level 3: Launch the interactive deployment TUI."""
    surface = DeploySurface(context, initial)
    asyncio.run(surface.run())

    if surface.cancelled:
        print("Cancelled")
        return 1

    # After TUI, run the actual deployment with styled output
    print()  # Blank line after TUI
    return deploy_styled(surface.final_config, width)


def main(args: list[str] | None = None) -> int:
    """Entry point for deploy demo."""
    if args is None:
        args = sys.argv[1:]

    fidelity = parse_fidelity(args)
    config = parse_config(args)
    width = terminal_width()

    if fidelity == Fidelity.MINIMAL:
        return deploy_minimal(config)
    elif fidelity == Fidelity.STANDARD:
        return deploy_standard(config)
    elif fidelity == Fidelity.STYLED:
        return deploy_styled(config, width)
    else:  # INTERACTIVE
        if is_interactive():
            return deploy_interactive(SAMPLE_CONTEXT, config, width)
        else:
            # Fall back to styled if not a TTY
            return deploy_styled(config, width)


if __name__ == "__main__":
    sys.exit(main())

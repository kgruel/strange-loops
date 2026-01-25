"""SSH connection manager for homelab VMs.

Manages persistent asyncio subprocesses per VM:
  - Health poller: runs `docker ps` periodically
  - Event streamer: runs `docker events` continuously
  - Resources poller: runs `docker stats` periodically

All commands query the Docker daemon directly (no compose project required).
Events are delivered via an async on_event callback for downstream projections.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

from .app_spec import VMInfo


# -- Parsing helpers -----------------------------------------------------------

def _parse_pct(s: str) -> float:
    """Parse '12.34%' to 12.34. Returns 0.0 on failure."""
    try:
        return float(s.rstrip("%"))
    except (ValueError, TypeError):
        return 0.0


# -- SSH helpers ---------------------------------------------------------------

def _ssh_base_args(vm: VMInfo) -> list[str]:
    """Build common SSH args for a VM."""
    args = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=5",
        "-o", "LogLevel=ERROR",
        "-o", "BatchMode=yes",
    ]
    if vm.key_file:
        args.extend(["-i", vm.key_file])
    args.append(f"{vm.user}@{vm.host}")
    return args


# -- SSH Connection Manager ----------------------------------------------------

class SSHConnectionManager:
    """Manages SSH subprocess connections to homelab VMs.

    For each connected VM, spawns:
      - A health poller (docker compose ps, periodic)
      - A log streamer (docker compose logs -f, continuous)

    Events are delivered via the async on_event callback.
    """

    def __init__(
        self,
        on_event: Callable[[str, str, dict[str, Any]], Awaitable[None]],
        poll_interval: float = 5.0,
        tail_lines: int = 50,
    ):
        """
        Args:
            on_event: async callback(vm_name, projection_name, event_dict)
            poll_interval: seconds between health polls
            tail_lines: initial log lines to tail
        """
        self._on_event = on_event
        self._poll_interval = poll_interval
        self._tail_lines = tail_lines
        self._tasks: dict[str, list[asyncio.Task]] = {}

    async def connect(self, vm: VMInfo) -> None:
        """Start SSH connections to a VM."""
        if vm.name in self._tasks:
            await self.disconnect(vm.name)

        tasks = [
            asyncio.create_task(self._run_health_poller(vm)),
            asyncio.create_task(self._run_log_streamer(vm)),
            asyncio.create_task(self._run_resources_poller(vm)),
        ]
        self._tasks[vm.name] = tasks

    async def disconnect(self, vm_name: str) -> None:
        """Stop SSH connections to a VM."""
        tasks = self._tasks.pop(vm_name, [])
        for task in tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def disconnect_all(self) -> None:
        """Disconnect all VMs."""
        for name in list(self._tasks):
            await self.disconnect(name)

    # -- Health poller ---------------------------------------------------------

    async def _run_health_poller(self, vm: VMInfo) -> None:
        """Periodically run `docker ps --format json` and emit events."""
        remote_cmd = 'docker ps --format "{{json .}}"'
        ssh_args = _ssh_base_args(vm)

        try:
            while True:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *ssh_args, remote_cmd,
                        stdin=asyncio.subprocess.DEVNULL,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(), timeout=15.0
                    )

                    if proc.returncode != 0:
                        err = stderr.decode(errors="replace").strip()
                        await self._on_event(vm.name, "vm-health", {
                            "container": "_connection",
                            "service": "_ssh",
                            "state": "error",
                            "health": err or f"exit {proc.returncode}",
                            "healthy": False,
                        })
                    else:
                        self._parse_health_output(vm.name, stdout.decode(errors="replace"))

                except asyncio.TimeoutError:
                    await self._on_event(vm.name, "vm-health", {
                        "container": "_connection",
                        "service": "_ssh",
                        "state": "timeout",
                        "health": "health check timed out",
                        "healthy": False,
                    })
                except OSError as e:
                    await self._on_event(vm.name, "vm-health", {
                        "container": "_connection",
                        "service": "_ssh",
                        "state": "error",
                        "health": str(e),
                        "healthy": False,
                    })

                await asyncio.sleep(self._poll_interval)

        except asyncio.CancelledError:
            return

    def _parse_health_output(self, vm_name: str, output: str) -> None:
        """Parse docker ps JSON output into container.status events."""
        for line in output.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                c = json.loads(line)
            except json.JSONDecodeError:
                continue

            state = c.get("State", "unknown")
            status = c.get("Status", "")
            # Health is embedded in Status: "Up 2 hours (healthy)" or "(unhealthy)"
            if "(healthy)" in status:
                health = "healthy"
            elif "(unhealthy)" in status:
                health = "unhealthy"
            else:
                health = ""
            healthy = state == "running" and health in ("", "healthy")
            # Names field from docker ps (may have comma-separated aliases)
            names = c.get("Names", "")
            container_name = names.split(",")[0] if names else ""
            event = {
                "container": container_name,
                "service": container_name,  # No service info from docker ps
                "state": state,
                "health": health or None,
                "healthy": healthy,
            }
            asyncio.create_task(self._on_event(vm_name, "vm-health", event))

    # -- Resources poller ------------------------------------------------------

    async def _run_resources_poller(self, vm: VMInfo) -> None:
        """Periodically run `docker stats --no-stream --format json` and emit events."""
        remote_cmd = 'docker stats --no-stream --format "{{json .}}"'
        ssh_args = _ssh_base_args(vm)

        try:
            while True:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *ssh_args, remote_cmd,
                        stdin=asyncio.subprocess.DEVNULL,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(), timeout=15.0
                    )

                    if proc.returncode == 0:
                        self._parse_resources_output(vm.name, stdout.decode(errors="replace"))

                except (asyncio.TimeoutError, OSError):
                    pass  # Skip silently; health poller already reports connectivity

                await asyncio.sleep(self._poll_interval)

        except asyncio.CancelledError:
            return

    def _parse_resources_output(self, vm_name: str, output: str) -> None:
        """Parse docker stats JSON output into container.stats events."""
        for line in output.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            event = {
                "container": data.get("Name", ""),
                "cpu_pct": _parse_pct(data.get("CPUPerc", "0%")),
                "mem_pct": _parse_pct(data.get("MemPerc", "0%")),
                "mem_usage": data.get("MemUsage", ""),
                "net_io": data.get("NetIO", ""),
                "pids": int(data.get("PIDs", 0) or 0),
            }
            asyncio.create_task(self._on_event(vm_name, "vm-resources", event))

    # -- Event streamer --------------------------------------------------------

    async def _run_log_streamer(self, vm: VMInfo) -> None:
        """Stream `docker events` and emit as log events."""
        remote_cmd = 'docker events --format "{{json .}}"'
        ssh_args = _ssh_base_args(vm)

        try:
            proc = await asyncio.create_subprocess_exec(
                *ssh_args, remote_cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )

            assert proc.stdout is not None
            while True:
                raw = await proc.stdout.readline()
                if not raw:
                    break
                line = raw.decode(errors="replace").rstrip("\n")
                if not line:
                    continue

                event = self._parse_docker_event(line)
                if event:
                    await self._on_event(vm_name=vm.name, projection="vm-events", event=event)

            await proc.wait()

        except asyncio.CancelledError:
            if proc.returncode is None:
                proc.terminate()
                await proc.wait()

    @staticmethod
    def _parse_docker_event(line: str) -> dict | None:
        """Parse docker events JSON into log event dict."""
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None

        # Only container events
        if data.get("Type") != "container":
            return None

        action = data.get("Action", data.get("status", ""))
        actor = data.get("Actor", {})
        attrs = actor.get("Attributes", {})
        container = attrs.get("name", "")

        if not container or not action:
            return None

        # Build message from action and relevant attributes
        if action == "health_status":
            health = attrs.get("health_status", attrs.get("healthStatus", ""))
            message = f"health: {health}" if health else "health check"
        elif action in ("start", "stop", "die", "kill", "restart", "pause", "unpause"):
            message = action
        elif action == "exec_start":
            message = f"exec: {attrs.get('execID', '')[:12]}"
        elif action == "exec_die":
            code = attrs.get("exitCode", "")
            message = f"exec exited ({code})" if code else "exec exited"
        else:
            message = action

        # Map action to log level
        if action in ("die", "kill", "oom"):
            level = "error"
        elif action in ("health_status",) and "unhealthy" in str(attrs):
            level = "warn"
        elif action in ("stop", "pause", "restart"):
            level = "warn"
        else:
            level = "info"

        return {"source": container, "message": message, "level": level}

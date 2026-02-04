"""Media audit command — scan media library for corrupt files.

Detects files where the size doesn't match expected bitrate for quality/runtime.
Uses Radarr API for movie metadata and optionally ffprobe via SSH for deep scans.
"""

from __future__ import annotations

import asyncio
import shlex
import sys
from argparse import ArgumentParser
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..infra import HostConfig, run_ssh, ssh_base_args
from ..inventory import load_inventory, host_config_from_inventory, ANSIBLE_INVENTORY_CACHE
from ..radarr import RadarrClient, RadarrError, Movie, QualityDefinition, parse_runtime
from ..lenses.media import AuditData, AuditResult, DeepScanResult, media_audit_view
from ..theme import DEFAULT_THEME


# SSH config for media host
MEDIA_HOST_STACK = "media"
FFMPEG_PATH = "/usr/lib/jellyfin-ffmpeg/ffmpeg"


def add_args(parser: ArgumentParser) -> None:
    """Add media audit-specific arguments."""
    parser.add_argument("--all", "-a", action="store_true", help="Show all files, not just suspicious")
    parser.add_argument("--quality", "-Q", help="Filter to specific quality (e.g., Remux-1080p)")
    parser.add_argument("--deep", "-d", action="store_true", help="Run deep scan on suspicious files (decode tests)")
    parser.add_argument("--inventory", type=Path, default=None, help="Override inventory.yml path")
    parser.add_argument("--connect-timeout", type=float, default=5.0, help="SSH connection timeout (seconds)")


def _audit_movie(movie: Movie, quality_defs: dict[str, QualityDefinition]) -> AuditResult | None:
    """Audit a single movie file against quality definitions."""
    if not movie.has_file or not movie.movie_file:
        return None

    mf = movie.movie_file
    quality_name = mf.quality_name
    actual_size = mf.size

    runtime_secs = parse_runtime(mf.runtime_str)
    runtime_mins = runtime_secs / 60 if runtime_secs else None

    # Calculate expected size using quality definitions
    quality_def = quality_defs.get(quality_name)
    expected_min = None
    size_ratio = None

    if quality_def and runtime_mins:
        # Quality definitions are in MB per minute
        if quality_def.min_size > 0:
            expected_min = int(quality_def.min_size * runtime_mins * 1024 * 1024)

        if expected_min and expected_min > 0:
            size_ratio = actual_size / expected_min

    # Determine status based on size ratio
    status: str = "unknown"
    reason = None

    if size_ratio is not None:
        if size_ratio < 0.3:
            status = "suspicious"
            reason = f"File is {size_ratio:.0%} of minimum expected size"
        elif size_ratio < 0.6:
            status = "suspicious"
            reason = f"File is {size_ratio:.0%} of minimum expected size"
        else:
            status = "ok"
    elif quality_def is None:
        status = "unknown"
        reason = f"No quality definition for '{quality_name}'"
    else:
        status = "unknown"
        reason = "Could not determine expected size"

    return AuditResult(
        movie_id=movie.id,
        title=movie.title,
        year=movie.year,
        quality=quality_name,
        runtime_seconds=runtime_secs,
        actual_size_bytes=actual_size,
        expected_min_bytes=expected_min,
        size_ratio=size_ratio,
        status=status,  # type: ignore
        reason=reason,
        file_path=mf.path,
    )


async def _deep_scan_file(
    host: HostConfig,
    file_path: str,
    runtime_seconds: int,
    connect_timeout: float,
) -> DeepScanResult:
    """Perform deep validation of a video file via SSH + ffmpeg.

    Decode test: Can we decode frames at 25%, 50%, 75%, 90%?
    """
    result = DeepScanResult()

    # Map from Radarr path (/movies/...) to Jellyfin container path (/media/movies/...)
    container_path = file_path.replace("/movies/", "/media/movies/", 1)
    escaped_path = shlex.quote(container_path)

    # Error patterns that indicate file corruption/truncation
    error_patterns = [
        "file ended prematurely",
        "end of file",
        "invalid data",
        "error while decoding",
        "corrupt",
        "truncated",
    ]

    def has_error(output: str) -> bool:
        output_lower = output.lower()
        return any(pat in output_lower for pat in error_patterns)

    # Try to decode frames at various checkpoints
    checkpoints = [0.25, 0.50, 0.75, 0.90]
    last_decodable_pct = 0.0
    decode_test_passed = True

    ssh_args = ssh_base_args(host, connect_timeout_s=connect_timeout)

    for pct in checkpoints:
        seek_pos = int(runtime_seconds * pct)
        # Try to decode 1 frame at this position
        decode_cmd = (
            f"docker exec jellyfin {FFMPEG_PATH} -v error "
            f"-ss {seek_pos} -i {escaped_path} "
            f"-frames:v 1 -f null -"
        )
        cmd = [*ssh_args, f"{host.user}@{host.ip}", decode_cmd]

        rc, stdout, stderr = await run_ssh(cmd, timeout_s=60.0)
        output = stdout + stderr

        # Check both exit code AND error patterns in output
        if rc == 0 and not has_error(output):
            last_decodable_pct = pct
        else:
            decode_test_passed = False
            return DeepScanResult(
                decode_test_passed=False,
                last_decodable_pct=last_decodable_pct,
                error_message=f"Decode failed at {pct:.0%}: {output[:200]}",
            )

    return DeepScanResult(
        decode_test_passed=True,
        last_decodable_pct=1.0,
    )


def make_fetcher(args) -> Callable[[], AuditData]:
    """Create a zero-arg fetcher from parsed CLI args."""
    show_all = getattr(args, "all", False)
    quality = getattr(args, "quality", None)
    deep = getattr(args, "deep", False)
    inventory = getattr(args, "inventory", None)
    connect_timeout = getattr(args, "connect_timeout", 5.0)

    def fetch() -> AuditData:
        return asyncio.run(_fetch_audit(
            show_all=show_all,
            quality=quality,
            deep=deep,
            inventory_path=inventory,
            connect_timeout=connect_timeout,
        ))

    return fetch


async def _fetch_audit(
    *,
    show_all: bool = False,
    quality: str | None = None,
    deep: bool = False,
    inventory_path: Path | None = None,
    connect_timeout: float = 5.0,
) -> AuditData:
    """Fetch and audit all movies from Radarr."""
    client = RadarrClient()

    try:
        movies, quality_defs = await asyncio.gather(
            client.get_movies(),
            client.get_quality_definitions(),
        )
    except RadarrError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return AuditData(results=[])

    results: list[AuditResult] = []

    for movie in movies:
        result = _audit_movie(movie, quality_defs)
        if result:
            if quality and result.quality != quality:
                continue
            results.append(result)

    if deep:
        suspicious = [r for r in results if r.status == "suspicious"]
        if suspicious:
            print(f"Running deep scan on {len(suspicious)} suspicious files...", file=sys.stderr)

            inv_path = inventory_path or ANSIBLE_INVENTORY_CACHE
            inv = load_inventory(inv_path)
            host = host_config_from_inventory(inv, MEDIA_HOST_STACK)

            if host.ip:
                for i, result in enumerate(suspicious):
                    if result.file_path and result.runtime_seconds:
                        print(f"  [{i + 1}/{len(suspicious)}] {result.title[:40]}...", file=sys.stderr)
                        deep_result = await _deep_scan_file(
                            host,
                            result.file_path,
                            result.runtime_seconds,
                            connect_timeout,
                        )
                        result.deep_scan = deep_result

                        if not deep_result.decode_test_passed:
                            if (deep_result.last_decodable_pct or 0) < 0.5:
                                result.status = "truncated"
                                result.reason = f"Truncated: fails at {deep_result.last_decodable_pct:.0%}"
                            else:
                                result.status = "corrupt"
                                result.reason = deep_result.error_message or "Deep scan failed"
                        else:
                            result.reason = f"Mislabeled: plays OK but only {result.size_ratio:.0%} of expected size"

    return AuditData(
        results=results,
        show_all=show_all,
        deep_scan_enabled=deep,
    )


def to_json(data: AuditData) -> dict[str, Any]:
    """Convert AuditData to JSON-serializable dict."""
    return {
        "results": [
            {
                "movie_id": r.movie_id,
                "title": r.title,
                "year": r.year,
                "quality": r.quality,
                "actual_size_bytes": r.actual_size_bytes,
                "expected_min_bytes": r.expected_min_bytes,
                "size_ratio": r.size_ratio,
                "status": r.status,
                "reason": r.reason,
                "deep_scan": asdict(r.deep_scan) if r.deep_scan else None,
            }
            for r in data.results
        ],
        "counts": {
            "total": len(data.results),
            "ok": sum(1 for r in data.results if r.status == "ok"),
            "suspicious": sum(1 for r in data.results if r.status == "suspicious"),
            "corrupt": sum(1 for r in data.results if r.status in ("corrupt", "truncated")),
            "unknown": sum(1 for r in data.results if r.status == "unknown"),
        },
    }

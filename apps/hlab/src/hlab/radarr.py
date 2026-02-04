"""Radarr API client — interface to Radarr movie management.

Provides async HTTP client for Radarr API operations needed by media commands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

# Default Radarr configuration (media host)
DEFAULT_RADARR_HOST = "192.168.1.40:7878"
DEFAULT_RADARR_API_KEY = "38f9f156c694487baf2bfb9f4355a02d"


class RadarrError(Exception):
    """Error communicating with Radarr API."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class QualityDefinition:
    """Quality size limits from Radarr."""

    quality_id: int
    title: str
    min_size: float  # MB per minute
    max_size: float | None  # MB per minute, None = unlimited
    preferred_size: float | None  # MB per minute


@dataclass(frozen=True)
class MovieFile:
    """Movie file information from Radarr."""

    id: int
    movie_id: int
    path: str
    size: int  # bytes
    quality_name: str
    runtime_str: str | None = None  # e.g., "1:41:41"
    media_info: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Movie:
    """Movie information from Radarr."""

    id: int
    title: str
    year: int | None
    has_file: bool
    movie_file: MovieFile | None = None
    path: str | None = None


# Fallback size limits (MB per minute) when Radarr definitions are at defaults
# Based on TRaSH Guides recommendations
FALLBACK_QUALITY_SIZES: dict[str, tuple[float, float | None]] = {
    # Quality name: (min_mb_per_min, max_mb_per_min)
    "Remux-2160p": (400.0, None),  # No max for remux
    "Remux-1080p": (170.0, None),
    "Bluray-2160p": (100.0, 400.0),
    "Bluray-1080p": (35.0, 170.0),
    "WEBDL-2160p": (85.0, 400.0),
    "WEBDL-1080p": (15.0, 85.0),
    "WEBRip-1080p": (15.0, 85.0),
    "HDTV-1080p": (15.0, 85.0),
    "Bluray-720p": (15.0, 85.0),
    "WEBDL-720p": (10.0, 50.0),
    "WEBRip-720p": (10.0, 50.0),
    "HDTV-720p": (10.0, 50.0),
    "DVD": (2.0, 35.0),
    "SDTV": (1.0, 15.0),
}


@dataclass
class RadarrClient:
    """Async client for Radarr API."""

    host: str = DEFAULT_RADARR_HOST
    api_key: str = DEFAULT_RADARR_API_KEY
    timeout: float = 60.0

    @property
    def base_url(self) -> str:
        return f"http://{self.host}/api/v3"

    async def _get(self, endpoint: str, **params) -> Any:
        """Make a GET request to Radarr API."""
        url = f"{self.base_url}/{endpoint}"
        params["apikey"] = self.api_key

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                raise RadarrError(f"HTTP {e.response.status_code}: {e.response.text[:200]}", e.response.status_code) from e
            except httpx.RequestError as e:
                raise RadarrError(f"Request failed: {e}") from e

    async def _delete(self, endpoint: str, **params) -> Any:
        """Make a DELETE request to Radarr API."""
        url = f"{self.base_url}/{endpoint}"
        params["apikey"] = self.api_key

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.delete(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                if resp.content:
                    return resp.json()
                return None
            except httpx.HTTPStatusError as e:
                raise RadarrError(f"HTTP {e.response.status_code}: {e.response.text[:200]}", e.response.status_code) from e
            except httpx.RequestError as e:
                raise RadarrError(f"Request failed: {e}") from e

    async def _post(self, endpoint: str, data: dict[str, Any]) -> Any:
        """Make a POST request to Radarr API."""
        url = f"{self.base_url}/{endpoint}"

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    url,
                    params={"apikey": self.api_key},
                    json=data,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                raise RadarrError(f"HTTP {e.response.status_code}: {e.response.text[:200]}", e.response.status_code) from e
            except httpx.RequestError as e:
                raise RadarrError(f"Request failed: {e}") from e

    async def get_movies(self) -> list[Movie]:
        """Fetch all movies from Radarr."""
        data = await self._get("movie")
        movies: list[Movie] = []

        for m in data:
            movie_file: MovieFile | None = None
            if mf := m.get("movieFile"):
                quality_name = mf.get("quality", {}).get("quality", {}).get("name", "Unknown")
                media_info = mf.get("mediaInfo", {})
                movie_file = MovieFile(
                    id=mf.get("id", 0),
                    movie_id=m.get("id", 0),
                    path=mf.get("path", ""),
                    size=mf.get("size", 0),
                    quality_name=quality_name,
                    runtime_str=media_info.get("runTime"),
                    media_info=media_info,
                )

            movies.append(Movie(
                id=m.get("id", 0),
                title=m.get("title", "Unknown"),
                year=m.get("year"),
                has_file=m.get("hasFile", False),
                movie_file=movie_file,
                path=m.get("path"),
            ))

        return movies

    async def get_quality_definitions(self) -> dict[str, QualityDefinition]:
        """Fetch quality definitions from Radarr API."""
        data = await self._get("qualitydefinition")
        result: dict[str, QualityDefinition] = {}

        for d in data:
            title = d.get("title", "")
            min_size = d.get("minSize", 0) or 0
            max_size = d.get("maxSize")
            preferred_size = d.get("preferredSize")

            # If Radarr has defaults (minSize=0), use our fallbacks
            if min_size == 0 and title in FALLBACK_QUALITY_SIZES:
                fallback_min, fallback_max = FALLBACK_QUALITY_SIZES[title]
                min_size = fallback_min
                if max_size is None:
                    max_size = fallback_max

            result[title] = QualityDefinition(
                quality_id=d.get("id", 0),
                title=title,
                min_size=min_size,
                max_size=max_size,
                preferred_size=preferred_size,
            )

        return result

    async def delete_movie_file(self, movie_file_id: int) -> None:
        """Delete a movie file by ID."""
        await self._delete(f"moviefile/{movie_file_id}")

    async def search_movie(self, movie_id: int) -> dict[str, Any]:
        """Trigger a search for a movie."""
        return await self._post("command", {
            "name": "MoviesSearch",
            "movieIds": [movie_id],
        })

    async def get_movie(self, movie_id: int) -> Movie | None:
        """Fetch a single movie by ID."""
        try:
            m = await self._get(f"movie/{movie_id}")
        except RadarrError:
            return None

        movie_file: MovieFile | None = None
        if mf := m.get("movieFile"):
            quality_name = mf.get("quality", {}).get("quality", {}).get("name", "Unknown")
            media_info = mf.get("mediaInfo", {})
            movie_file = MovieFile(
                id=mf.get("id", 0),
                movie_id=m.get("id", 0),
                path=mf.get("path", ""),
                size=mf.get("size", 0),
                quality_name=quality_name,
                runtime_str=media_info.get("runTime"),
                media_info=media_info,
            )

        return Movie(
            id=m.get("id", 0),
            title=m.get("title", "Unknown"),
            year=m.get("year"),
            has_file=m.get("hasFile", False),
            movie_file=movie_file,
            path=m.get("path"),
        )


def parse_runtime(runtime_str: str | None) -> int | None:
    """Parse runtime string like '1:41:41' to seconds."""
    if not runtime_str:
        return None
    parts = runtime_str.split(":")
    try:
        if len(parts) == 3:
            h, m, s = map(int, parts)
            return h * 3600 + m * 60 + s
        elif len(parts) == 2:
            m, s = map(int, parts)
            return m * 60 + s
    except ValueError:
        pass
    return None


def format_size(bytes_: int) -> str:
    """Format bytes as human-readable size."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_ < 1024:
            return f"{bytes_:.1f} {unit}"
        bytes_ /= 1024
    return f"{bytes_:.1f} PB"

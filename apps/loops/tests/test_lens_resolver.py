"""Tests for lens resolver — file search, built-in fallback, candidate naming."""

from pathlib import Path

import pytest

from loops.lens_resolver import resolve_lens, _view_candidates, _build_search_path


class TestViewCandidates:
    """_view_candidates builds ordered function name lists."""

    def test_fold_view_candidates(self):
        names = _view_candidates("prompt", "fold_view")
        assert names == ("fold_view", "prompt_view")

    def test_stream_view_candidates(self):
        names = _view_candidates("prompt", "stream_view")
        assert names == ("stream_view", "stream_prompt_view", "prompt_view")

    def test_dedupes(self):
        names = _view_candidates("fold", "fold_view")
        # fold_view appears as both standard and lens-specific — deduped
        assert names == ("fold_view",)


class TestBuildSearchPath:
    def test_includes_vertex_dir(self, tmp_path):
        dirs = _build_search_path(tmp_path / "my_vertex")
        assert dirs[0] == tmp_path / "my_vertex" / "lenses"

    def test_none_vertex_dir(self):
        dirs = _build_search_path(None)
        assert len(dirs) >= 2  # cwd/lenses + user-global


class TestResolveBuiltin:
    """Resolve built-in lenses from the loops.lenses package."""

    def test_prompt_fold(self):
        fn = resolve_lens("prompt", "fold_view")
        assert fn is not None
        assert fn.__name__ == "prompt_view"

    def test_prompt_stream(self):
        fn = resolve_lens("prompt", "stream_view")
        assert fn is not None
        assert fn.__name__ == "stream_prompt_view"

    def test_fold_fold(self):
        fn = resolve_lens("fold", "fold_view")
        assert fn is not None
        assert fn.__name__ == "fold_view"

    def test_stream_stream(self):
        fn = resolve_lens("stream", "stream_view")
        assert fn is not None
        assert fn.__name__ == "stream_view"

    def test_nonexistent(self):
        fn = resolve_lens("nonexistent_lens_xyz", "fold_view")
        assert fn is None


class TestResolveFromFile:
    """Resolve lenses from Python files on disk."""

    def test_file_in_vertex_lenses_dir(self, tmp_path):
        # Create a custom lens file
        lenses_dir = tmp_path / "lenses"
        lenses_dir.mkdir()
        lens_file = lenses_dir / "custom.py"
        lens_file.write_text(
            "def fold_view(data, zoom, width):\n"
            "    return 'custom'\n"
        )

        fn = resolve_lens("custom", "fold_view", vertex_dir=tmp_path)
        assert fn is not None
        assert fn(None, None, None) == "custom"

    def test_path_style_name(self, tmp_path):
        # Create a lens file at a specific path
        lens_file = tmp_path / "my_lens.py"
        lens_file.write_text(
            "def fold_view(data, zoom, width):\n"
            "    return 'path-resolved'\n"
        )

        fn = resolve_lens(f"./{lens_file.name}", "fold_view", vertex_dir=tmp_path)
        assert fn is not None
        assert fn(None, None, None) == "path-resolved"

    def test_lens_specific_name_fallback(self, tmp_path):
        # Create a lens with lens-specific name (e.g., my_view instead of fold_view)
        lenses_dir = tmp_path / "lenses"
        lenses_dir.mkdir()
        lens_file = lenses_dir / "my.py"
        lens_file.write_text(
            "def my_view(data, zoom, width):\n"
            "    return 'lens-specific'\n"
        )

        fn = resolve_lens("my", "fold_view", vertex_dir=tmp_path)
        assert fn is not None
        assert fn(None, None, None) == "lens-specific"

    def test_missing_view_in_file(self, tmp_path):
        # File exists but doesn't export the right function
        lenses_dir = tmp_path / "lenses"
        lenses_dir.mkdir()
        lens_file = lenses_dir / "partial.py"
        lens_file.write_text(
            "def stream_view(data, zoom, width):\n"
            "    return 'stream-only'\n"
        )

        fn = resolve_lens("partial", "fold_view", vertex_dir=tmp_path)
        assert fn is None

    def test_nonexistent_path(self, tmp_path):
        fn = resolve_lens("./nonexistent.py", "fold_view", vertex_dir=tmp_path)
        assert fn is None

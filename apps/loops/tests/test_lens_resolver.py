"""Tests for lens resolver — file search, built-in fallback, candidate naming, call_lens."""

from pathlib import Path

import pytest

from loops.lens_resolver import resolve_lens, call_lens, _view_candidates, _build_search_path


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


class TestCallLens:
    """call_lens passes optional kwargs when the lens accepts them."""

    def test_passes_vertex_name_when_accepted(self):
        def lens_with_ctx(data, zoom, width, *, vertex_name=None):
            return f"got:{vertex_name}"

        result = call_lens(lens_with_ctx, "d", "z", 80, vertex_name="project")
        assert result == "got:project"

    def test_drops_kwargs_when_not_accepted(self):
        def lens_without_ctx(data, zoom, width):
            return f"basic:{data}"

        result = call_lens(lens_without_ctx, "d", "z", 80, vertex_name="project")
        assert result == "basic:d"

    def test_no_kwargs_still_works(self):
        def lens(data, zoom, width):
            return "ok"

        result = call_lens(lens, "d", "z", 80)
        assert result == "ok"


class TestLensResolverEdges:
    """Edge cases for lens_resolver not previously covered."""

    def test_resolve_path_style_no_vertex_dir(self, tmp_path):
        """Path-style lens name with no vertex_dir → resolve() relative to cwd (L64)."""
        from loops.lens_resolver import resolve_lens
        # Create a real lens file at tmp_path
        lens_file = tmp_path / "custom_lens.py"
        lens_file.write_text("""
def fold_view(data, zoom, width):
    from painted import Block, Style
    return Block.text("ok", Style(), width=width)
""")
        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = resolve_lens("./custom_lens.py", "fold_view", vertex_dir=None)
            assert result is not None
        finally:
            os.chdir(old_cwd)

    def test_load_from_file_spec_none(self, tmp_path):
        """_load_from_file returns None when spec is None (L134-135) — covered indirectly
        via nonexistent path, or test the import-error fallback path (L141-143)."""
        from loops.lens_resolver import resolve_lens
        # A file with a syntax error triggers exec_module to fail → L141-143
        bad_lens = tmp_path / "broken.py"
        bad_lens.write_text("def fold_view(: :\n    pass\n")  # syntax error
        result = resolve_lens(str(bad_lens), "fold_view", vertex_dir=None)
        assert result is None


class TestLoadFromFileSpecNone:
    def test_load_lens_module_non_python(self, tmp_path):
        """_load_lens_module with non-.py file hits spec=None path."""
        from loops.lens_resolver import _load_lens_module
        # A .txt file can't be spec'd by importlib
        non_py = tmp_path / "test.txt"
        non_py.write_text("def fold_view(d, z, w): pass\n")
        result = _load_lens_module(non_py)
        assert result is None


class TestResolveLensFetch:
    """resolve_lens_fetch — composition lenses declare their own fetch."""

    def test_returns_none_when_lens_omits_fetch(self, tmp_path):
        """Simple lenses (view-only) yield None — caller uses default fetch."""
        from loops.lens_resolver import resolve_lens_fetch

        lens_dir = tmp_path / "lenses"
        lens_dir.mkdir()
        (lens_dir / "simple.py").write_text(
            "def fold_view(data, zoom, width): return None\n"
        )
        # Point the user-global search at tmp_path — fall back path search
        result = resolve_lens_fetch(
            str((lens_dir / "simple.py").resolve()),
            vertex_dir=None,
        )
        assert result is None

    def test_resolves_fetch_from_file(self, tmp_path):
        """Lens file exporting fetch returns the callable."""
        from loops.lens_resolver import resolve_lens_fetch

        lens_file = tmp_path / "composed.py"
        lens_file.write_text(
            "def fetch(vertex_path, **kwargs):\n"
            "    return {'v': str(vertex_path)}\n"
            "def fold_view(data, zoom, width): return None\n"
        )
        result = resolve_lens_fetch(str(lens_file), vertex_dir=None)
        assert result is not None
        assert result(Path("/tmp/x")) == {"v": "/tmp/x"}

    def test_resolves_fetch_by_name_in_vertex_dir(self, tmp_path):
        """Name-style resolution finds <vertex_dir>/lenses/<name>.py fetch."""
        from loops.lens_resolver import resolve_lens_fetch

        lens_dir = tmp_path / "lenses"
        lens_dir.mkdir()
        (lens_dir / "custom.py").write_text(
            "def fetch(vertex_path, **kwargs):\n"
            "    return 'declared'\n"
            "def fold_view(data, zoom, width): return None\n"
        )
        result = resolve_lens_fetch("custom", vertex_dir=tmp_path)
        assert result is not None
        assert result(Path("/tmp/x")) == "declared"

    def test_returns_none_when_lens_not_found(self, tmp_path):
        """Unresolvable name returns None (no exception)."""
        from loops.lens_resolver import resolve_lens_fetch

        result = resolve_lens_fetch("nonexistent_lens_xyz", vertex_dir=tmp_path)
        assert result is None

    def test_path_style_missing_returns_none(self, tmp_path):
        """Path-style lens that doesn't exist returns None (no built-in fallback)."""
        from loops.lens_resolver import resolve_lens_fetch

        result = resolve_lens_fetch(
            str(tmp_path / "nope.py"), vertex_dir=None,
        )
        assert result is None

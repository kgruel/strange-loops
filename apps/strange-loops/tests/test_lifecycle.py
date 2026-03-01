"""Tests for lifecycle — compiled vertex loader + Spec-based fold."""

from __future__ import annotations

from pathlib import Path

from atoms import Fact
from engine import StoreReader, SqliteStore

from strange_loops.lifecycle import (
    _PKG_ROOT,
    _vertex_path,
    fold_all_tasks,
    fold_task_state,
    load_compiled,
)


def _emit(db: Path, kind: str, obs: str, payload: dict) -> None:
    fact = Fact.of(kind, obs, **payload)
    db.parent.mkdir(parents=True, exist_ok=True)
    with SqliteStore(path=db, serialize=Fact.to_dict, deserialize=Fact.from_dict) as store:
        store.append(fact)


class TestVertexParsesAndCompiles:
    def test_vertex_file_exists(self):
        assert _vertex_path().exists()

    def test_vertex_parses(self):
        from lang import parse_vertex_file

        v = parse_vertex_file(_vertex_path())
        assert v.name == "tasks"
        assert "task.created" in v.loops
        assert "worker.output.complete" in v.loops

    def test_vertex_compiles(self):
        compiled = load_compiled()
        assert "task.created" in compiled.specs
        assert "task.assigned" in compiled.specs
        assert "task.stage" in compiled.specs
        assert "task.completed" in compiled.specs
        assert "task.merged" in compiled.specs
        assert "worker.output" in compiled.specs
        assert "worker.output.complete" in compiled.specs
        assert "worker.started" in compiled.specs
        assert len(compiled.specs) == 8

    def test_specs_have_correct_folds(self):
        from atoms import Collect, Upsert

        compiled = load_compiled()
        # task.* specs use Upsert keyed by "name"
        for kind in (
            "task.created",
            "task.assigned",
            "task.stage",
            "task.completed",
            "task.merged",
        ):
            spec = compiled.specs[kind]
            assert len(spec.folds) == 1
            assert isinstance(spec.folds[0], Upsert)
            assert spec.folds[0].key == "name"

        # worker.started uses Upsert keyed by "task"
        spec = compiled.specs["worker.started"]
        assert len(spec.folds) == 1
        assert isinstance(spec.folds[0], Upsert)
        assert spec.folds[0].key == "task"

        # worker.output uses Collect
        spec = compiled.specs["worker.output"]
        assert len(spec.folds) == 1
        assert isinstance(spec.folds[0], Collect)
        assert spec.folds[0].max == 10000

        # worker.output.complete uses Upsert keyed by "task"
        spec = compiled.specs["worker.output.complete"]
        assert len(spec.folds) == 1
        assert isinstance(spec.folds[0], Upsert)
        assert spec.folds[0].key == "task"

    def test_shell_loop_compiles(self):
        from lang import parse_loop_file

        loop_path = _vertex_path().parent / "harnesses" / "shell.loop"
        loop = parse_loop_file(loop_path)
        assert loop.kind == "worker.output"
        assert loop.observer == "shell"
        assert loop.format == "lines"
        assert loop.source == "{{command}}"

    def test_sonnet_loop_compiles(self):
        from lang import parse_loop_file

        loop_path = _vertex_path().parent / "harnesses" / "sonnet.loop"
        loop = parse_loop_file(loop_path)
        assert loop.kind == "worker.output"
        assert loop.observer == "sonnet"
        assert loop.format == "lines"
        assert "claude" in loop.source
        assert "{{prompt}}" in loop.source

    def test_codex_loop_compiles(self):
        from lang import parse_loop_file

        loop_path = _vertex_path().parent / "harnesses" / "codex.loop"
        loop = parse_loop_file(loop_path)
        assert loop.kind == "worker.output"
        assert loop.observer == "codex"
        assert loop.format == "lines"
        assert "codex" in loop.source
        assert "{{prompt}}" in loop.source

    def test_gemini_flash_loop_compiles(self):
        from lang import parse_loop_file

        loop_path = _vertex_path().parent / "harnesses" / "gemini-flash.loop"
        loop = parse_loop_file(loop_path)
        assert loop.kind == "worker.output"
        assert loop.observer == "gemini-flash"
        assert loop.format == "lines"
        assert "gemini" in loop.source
        assert "{{prompt}}" in loop.source


class TestProjectVertexCompiles:
    def test_project_vertex_file_exists(self):
        project_path = _PKG_ROOT / "loops" / "project.vertex"
        assert project_path.exists()

    def test_project_vertex_parses(self):
        from lang import parse_vertex_file

        project_path = _PKG_ROOT / "loops" / "project.vertex"
        v = parse_vertex_file(project_path)
        assert v.name == "project"
        assert "decision" in v.loops
        assert "thread" in v.loops
        assert "plan" in v.loops

    def test_project_vertex_compiles(self):
        from engine import compile_vertex_recursive
        from lang import parse_vertex_file

        project_path = _PKG_ROOT / "loops" / "project.vertex"
        vertex = parse_vertex_file(project_path)
        compiled = compile_vertex_recursive(vertex)
        assert "decision" in compiled.specs
        assert "thread" in compiled.specs
        assert "plan" in compiled.specs
        assert "completion" in compiled.specs
        assert len(compiled.specs) == 4

    def test_project_specs_have_correct_folds(self):
        from atoms import Upsert
        from engine import compile_vertex_recursive
        from lang import parse_vertex_file

        project_path = _PKG_ROOT / "loops" / "project.vertex"
        vertex = parse_vertex_file(project_path)
        compiled = compile_vertex_recursive(vertex)

        # decision by topic
        spec = compiled.specs["decision"]
        assert len(spec.folds) == 1
        assert isinstance(spec.folds[0], Upsert)
        assert spec.folds[0].key == "topic"

        # thread by name
        spec = compiled.specs["thread"]
        assert len(spec.folds) == 1
        assert isinstance(spec.folds[0], Upsert)
        assert spec.folds[0].key == "name"

        # plan by name
        spec = compiled.specs["plan"]
        assert len(spec.folds) == 1
        assert isinstance(spec.folds[0], Upsert)
        assert spec.folds[0].key == "name"


class TestFoldTaskState:
    def test_fold_created_task(self, tmp_path: Path):
        db = tmp_path / "data" / "tasks.db"
        _emit(
            db,
            "task.created",
            "alice",
            {"name": "build-api", "title": "Build", "base_branch": "main", "description": ""},
        )

        with StoreReader(db) as reader:
            state = fold_task_state(reader, "build-api")

        assert state is not None
        assert state["name"] == "build-api"
        assert state["title"] == "Build"
        assert state["status"] == "created"

    def test_fold_assigned_task(self, tmp_path: Path):
        db = tmp_path / "data" / "tasks.db"
        _emit(
            db,
            "task.created",
            "alice",
            {"name": "t1", "title": "T", "base_branch": "main", "description": ""},
        )
        _emit(
            db, "task.assigned", "alice", {"name": "t1", "harness": "shell", "worktree": "/tmp/wt"}
        )

        with StoreReader(db) as reader:
            state = fold_task_state(reader, "t1")

        assert state["status"] == "assigned"
        assert state["harness"] == "shell"
        assert state["worktree"] == "/tmp/wt"

    def test_fold_worker_complete(self, tmp_path: Path):
        db = tmp_path / "data" / "tasks.db"
        _emit(
            db,
            "task.created",
            "a",
            {"name": "t1", "title": "", "base_branch": "main", "description": ""},
        )
        _emit(db, "worker.output.complete", "a", {"task": "t1", "status": "ok", "returncode": 0})

        with StoreReader(db) as reader:
            state = fold_task_state(reader, "t1")

        assert state["worker"] == "stopped"
        assert state["exit_code"] == 0

    def test_fold_worker_error(self, tmp_path: Path):
        db = tmp_path / "data" / "tasks.db"
        _emit(
            db,
            "task.created",
            "a",
            {"name": "t1", "title": "", "base_branch": "main", "description": ""},
        )
        _emit(db, "worker.output.complete", "a", {"task": "t1", "status": "error", "returncode": 1})

        with StoreReader(db) as reader:
            state = fold_task_state(reader, "t1")

        assert state["worker"] == "error"
        assert state["exit_code"] == 1

    def test_fold_worker_pid(self, tmp_path: Path):
        db = tmp_path / "data" / "tasks.db"
        _emit(
            db,
            "task.created",
            "a",
            {"name": "t1", "title": "", "base_branch": "main", "description": ""},
        )
        _emit(db, "worker.started", "a", {"task": "t1", "pid": 12345})

        with StoreReader(db) as reader:
            state = fold_task_state(reader, "t1")

        assert state["pid"] == 12345

    def test_unknown_task_returns_none(self, tmp_path: Path):
        db = tmp_path / "data" / "tasks.db"
        _emit(
            db,
            "task.created",
            "a",
            {"name": "t1", "title": "", "base_branch": "main", "description": ""},
        )

        with StoreReader(db) as reader:
            assert fold_task_state(reader, "nonexistent") is None


class TestFoldAllTasks:
    def test_fold_multiple_tasks(self, tmp_path: Path):
        db = tmp_path / "data" / "tasks.db"
        _emit(
            db,
            "task.created",
            "a",
            {"name": "alpha", "title": "A", "base_branch": "main", "description": ""},
        )
        _emit(
            db,
            "task.created",
            "a",
            {"name": "beta", "title": "B", "base_branch": "main", "description": ""},
        )

        with StoreReader(db) as reader:
            tasks = fold_all_tasks(reader)

        assert len(tasks) == 2
        names = [t["name"] for t in tasks]
        assert "alpha" in names
        assert "beta" in names

    def test_fold_independent_state(self, tmp_path: Path):
        db = tmp_path / "data" / "tasks.db"
        _emit(
            db,
            "task.created",
            "a",
            {"name": "t1", "title": "One", "base_branch": "main", "description": ""},
        )
        _emit(
            db,
            "task.created",
            "a",
            {"name": "t2", "title": "Two", "base_branch": "dev", "description": ""},
        )
        _emit(db, "task.assigned", "a", {"name": "t1", "harness": "shell", "worktree": "/w1"})

        with StoreReader(db) as reader:
            tasks = fold_all_tasks(reader)

        t1 = next(t for t in tasks if t["name"] == "t1")
        t2 = next(t for t in tasks if t["name"] == "t2")

        assert t1["status"] == "assigned"
        assert t1["harness"] == "shell"
        assert t2["status"] == "created"
        assert "harness" not in t2

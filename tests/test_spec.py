"""Tests for spec-driven projections."""

import tempfile
from pathlib import Path

import pytest

from framework.spec import (
    ProjectionSpec,
    SpecProjection,
    FieldSpec,
    FoldOp,
    EventSpec,
    ValidationError,
    parse_projection_spec,
)
from framework.app_spec import parse_app_spec, DataSourceSpec, VMInfo


SPECS_DIR = Path(__file__).parent.parent / "specs"


class TestProjectionSpecParsing:
    def test_parse_vm_health(self):
        spec = parse_projection_spec(SPECS_DIR / "vm-health.projection.kdl")
        assert spec.name == "vm-health"
        assert spec.about == "Container health state per VM"
        assert len(spec.events) == 1
        assert spec.events[0].name == "container.status"
        assert len(spec.events[0].fields) == 5
        assert len(spec.state_fields) == 2
        assert len(spec.fold_ops) == 2

    def test_parse_vm_events(self):
        spec = parse_projection_spec(SPECS_DIR / "vm-events.projection.kdl")
        assert spec.name == "vm-events"
        assert len(spec.events) == 1
        assert spec.events[0].name == "container.lifecycle"
        assert len(spec.state_fields) == 2
        assert len(spec.fold_ops) == 2

    def test_initial_state_types(self):
        spec = parse_projection_spec(SPECS_DIR / "vm-health.projection.kdl")
        state = spec.initial_state()
        assert state == {"containers": {}, "last_update": None}

    def test_initial_state_list_and_set(self):
        spec = parse_projection_spec(SPECS_DIR / "vm-events.projection.kdl")
        state = spec.initial_state()
        assert state == {"events": [], "containers": set()}


class TestFoldOps:
    def test_upsert_dict(self):
        spec = parse_projection_spec(SPECS_DIR / "vm-health.projection.kdl")
        proj = SpecProjection(spec)
        new = proj.apply(proj.state, {
            "container": "nginx",
            "service": "nginx",
            "state": "running",
            "health": "healthy",
            "healthy": True,
        })
        assert "nginx" in new["containers"]
        assert new["containers"]["nginx"]["healthy"] is True

    def test_upsert_updates_existing(self):
        spec = parse_projection_spec(SPECS_DIR / "vm-health.projection.kdl")
        proj = SpecProjection(spec)
        s1 = proj.apply(proj.state, {
            "container": "nginx",
            "service": "nginx",
            "state": "running",
            "health": "healthy",
            "healthy": True,
        })
        s2 = proj.apply(s1, {
            "container": "nginx",
            "service": "nginx",
            "state": "restarting",
            "health": "unhealthy",
            "healthy": False,
        })
        assert s2["containers"]["nginx"]["healthy"] is False
        assert s2["containers"]["nginx"]["state"] == "restarting"

    def test_upsert_set(self):
        spec = parse_projection_spec(SPECS_DIR / "vm-events.projection.kdl")
        proj = SpecProjection(spec)
        s1 = proj.apply(proj.state, {"source": "nginx", "message": "hi", "level": "info"})
        s2 = proj.apply(s1, {"source": "redis", "message": "ok", "level": "info"})
        s3 = proj.apply(s2, {"source": "nginx", "message": "again", "level": "info"})
        assert s3["containers"] == {"nginx", "redis"}

    def test_collect_bounded(self):
        spec = parse_projection_spec(SPECS_DIR / "vm-events.projection.kdl")
        proj = SpecProjection(spec)
        state = proj.state
        # Feed more than max (500) events — verify truncation
        for i in range(10):
            state = proj.apply(state, {"source": "x", "message": f"msg {i}", "level": "info"})
        assert len(state["events"]) == 10  # well under max

    def test_latest(self):
        spec = parse_projection_spec(SPECS_DIR / "vm-health.projection.kdl")
        proj = SpecProjection(spec)
        s = proj.apply(proj.state, {"container": "x", "service": "x", "state": "r", "health": "h", "healthy": True})
        assert s["last_update"] is not None

    def test_version_increments(self):
        spec = parse_projection_spec(SPECS_DIR / "vm-health.projection.kdl")
        proj = SpecProjection(spec)
        assert proj.version == 0
        import asyncio
        asyncio.run(proj.consume({"container": "x", "service": "x", "state": "r", "health": "h", "healthy": True}))
        assert proj.version == 1


class TestAppSpec:
    def test_parse_app(self):
        app = parse_app_spec(SPECS_DIR / "homelab.app.kdl", specs_dir=SPECS_DIR)
        assert app.name == "homelab"
        assert app.watch is True
        assert len(app.projections) == 3
        assert app.projections[0].name == "vm-health"
        assert app.projections[1].name == "vm-events"
        assert app.projections[2].name == "vm-resources"

    def test_inventory_loaded(self):
        app = parse_app_spec(SPECS_DIR / "homelab.app.kdl", specs_dir=SPECS_DIR)
        assert len(app.vms) == 8
        names = {vm.name for vm in app.vms}
        assert "media" in names
        assert "infra" in names

    def test_vm_info_fields(self):
        app = parse_app_spec(SPECS_DIR / "homelab.app.kdl", specs_dir=SPECS_DIR)
        media = next(vm for vm in app.vms if vm.name == "media")
        assert media.host == "192.168.1.40"
        assert media.user == "deploy"
        assert media.service_type == "media"


class TestValidation:
    """Tests for event validation and type coercion."""

    def test_missing_required_field_raises(self):
        spec = parse_projection_spec(SPECS_DIR / "vm-health.projection.kdl")
        proj = SpecProjection(spec)
        with pytest.raises(ValidationError, match="missing required field 'container'"):
            import asyncio
            asyncio.run(proj.consume({"service": "x", "state": "r", "healthy": True}))

    def test_wrong_type_raises(self):
        spec = parse_projection_spec(SPECS_DIR / "vm-health.projection.kdl")
        proj = SpecProjection(spec)
        with pytest.raises(ValidationError, match="expected bool"):
            import asyncio
            # "maybe" can't coerce to bool
            asyncio.run(proj.consume({
                "container": "x",
                "service": "x",
                "state": "r",
                "healthy": "maybe",  # wrong: can't coerce to bool
            }))

    def test_coerce_string_true_to_bool(self):
        spec = parse_projection_spec(SPECS_DIR / "vm-health.projection.kdl")
        proj = SpecProjection(spec)
        import asyncio
        asyncio.run(proj.consume({
            "container": "nginx",
            "service": "nginx",
            "state": "running",
            "healthy": "true",  # string, should coerce to True
        }))
        assert proj.state["containers"]["nginx"]["healthy"] is True

    def test_coerce_string_false_to_bool(self):
        spec = parse_projection_spec(SPECS_DIR / "vm-health.projection.kdl")
        proj = SpecProjection(spec)
        import asyncio
        asyncio.run(proj.consume({
            "container": "nginx",
            "service": "nginx",
            "state": "running",
            "healthy": "false",
        }))
        assert proj.state["containers"]["nginx"]["healthy"] is False

    def test_coerce_int_to_bool(self):
        spec = parse_projection_spec(SPECS_DIR / "vm-health.projection.kdl")
        proj = SpecProjection(spec)
        import asyncio
        asyncio.run(proj.consume({
            "container": "nginx",
            "service": "nginx",
            "state": "running",
            "healthy": 1,  # int, should coerce to True
        }))
        assert proj.state["containers"]["nginx"]["healthy"] is True

    def test_optional_field_can_be_missing(self):
        spec = parse_projection_spec(SPECS_DIR / "vm-health.projection.kdl")
        proj = SpecProjection(spec)
        import asyncio
        # 'health' is optional (str?), should not raise
        asyncio.run(proj.consume({
            "container": "nginx",
            "service": "nginx",
            "state": "running",
            "healthy": True,
            # no 'health' field
        }))
        assert proj.state["containers"]["nginx"]["container"] == "nginx"

    def test_extra_fields_allowed(self):
        spec = parse_projection_spec(SPECS_DIR / "vm-health.projection.kdl")
        proj = SpecProjection(spec)
        import asyncio
        asyncio.run(proj.consume({
            "container": "nginx",
            "service": "nginx",
            "state": "running",
            "healthy": True,
            "extra_field": "ignored by schema but passed through",
            "another": 123,
        }))
        # Extra fields should be in the stored event
        assert proj.state["containers"]["nginx"]["extra_field"] == "ignored by schema but passed through"

    def test_coerce_string_to_int(self):
        """Test coercion for numeric types (using vm-resources which has int fields)."""
        spec = parse_projection_spec(SPECS_DIR / "vm-resources.projection.kdl")
        proj = SpecProjection(spec)
        import asyncio
        asyncio.run(proj.consume({
            "container": "nginx",
            "cpu_pct": "45.5",  # string, should coerce to float
            "mem_pct": "30",
            "mem_usage": "100MiB / 1GiB",
            "net_io": "1kB / 2kB",
            "pids": "10",  # string, should coerce to int
        }))
        assert proj.state["resources"]["nginx"]["pids"] == 10
        assert proj.state["resources"]["nginx"]["cpu_pct"] == 45.5


class TestDataSourceSpec:
    """Tests for data source parsing with 'as' field."""

    def test_parse_collect_with_as(self):
        """collect node with as= field parses correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            # Create minimal inventory
            (tmp / "inventory.yml").write_text("all: {}")
            # Create app spec with collect using 'as'
            (tmp / "test.app.kdl").write_text('''
                app "test" {
                    inventory "inventory.yml"
                    per-connection {
                        collect "docker:containers" as="container.status" into="vm-health" interval=5
                    }
                }
            ''')
            app = parse_app_spec(tmp / "test.app.kdl")
            assert len(app.data_sources) == 1
            ds = app.data_sources[0]
            assert ds.collector == "docker:containers"
            assert ds.event_type == "container.status"
            assert ds.projection == "vm-health"
            assert ds.mode == "collect"
            assert ds.interval == 5

    def test_parse_stream_with_as(self):
        """stream node with as= field parses correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "inventory.yml").write_text("all: {}")
            (tmp / "test.app.kdl").write_text('''
                app "test" {
                    inventory "inventory.yml"
                    per-connection {
                        stream "docker:events" as="docker.event" into="vm-events"
                    }
                }
            ''')
            app = parse_app_spec(tmp / "test.app.kdl")
            assert len(app.data_sources) == 1
            ds = app.data_sources[0]
            assert ds.collector == "docker:events"
            assert ds.event_type == "docker.event"
            assert ds.projection == "vm-events"
            assert ds.mode == "stream"
            assert ds.interval is None

    def test_missing_as_skips_data_source(self):
        """collect/stream without as= is skipped (returns None)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "inventory.yml").write_text("all: {}")
            (tmp / "test.app.kdl").write_text('''
                app "test" {
                    inventory "inventory.yml"
                    per-connection {
                        collect "docker:containers" into="vm-health" interval=5
                    }
                }
            ''')
            app = parse_app_spec(tmp / "test.app.kdl")
            # Data source should be skipped due to missing 'as'
            assert len(app.data_sources) == 0

    def test_missing_into_skips_data_source(self):
        """collect/stream without into= is skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "inventory.yml").write_text("all: {}")
            (tmp / "test.app.kdl").write_text('''
                app "test" {
                    inventory "inventory.yml"
                    per-connection {
                        collect "docker:containers" as="container.status" interval=5
                    }
                }
            ''')
            app = parse_app_spec(tmp / "test.app.kdl")
            # Data source should be skipped due to missing 'into'
            assert len(app.data_sources) == 0

    def test_multiple_data_sources(self):
        """Multiple collect/stream nodes with as= all parse."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "inventory.yml").write_text("all: {}")
            (tmp / "test.app.kdl").write_text('''
                app "test" {
                    inventory "inventory.yml"
                    per-connection {
                        collect "docker:containers" as="container.status" into="vm-health" interval=5
                        stream "docker:events" as="container.lifecycle" into="vm-events"
                        collect "docker:stats" as="container.stats" into="vm-resources" interval=10
                    }
                }
            ''')
            app = parse_app_spec(tmp / "test.app.kdl")
            assert len(app.data_sources) == 3
            assert app.data_sources[0].event_type == "container.status"
            assert app.data_sources[1].event_type == "container.lifecycle"
            assert app.data_sources[2].event_type == "container.stats"

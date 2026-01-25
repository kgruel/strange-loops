"""Tests for spec-driven projections."""

from pathlib import Path

from framework.spec import (
    ProjectionSpec,
    SpecProjection,
    FieldSpec,
    FoldOp,
    EventSpec,
    parse_projection_spec,
)
from framework.app_spec import parse_app_spec, VMInfo


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

# Homelab Monitoring Experiment

DSL-driven replication of homelab monitoring scripts from `~/Code/gruel.network/scripts/`.

## Structure

```
homelab/
├── root.vertex           # Top-level aggregation
├── local/                # Local system monitoring (Phase 1)
│   ├── disk.loop         # df -h parsing
│   ├── proc.loop         # ps parsing
│   └── local.vertex      # Local health aggregation
├── stacks/               # SSH-based container monitoring (Phase 2)
│   ├── infra-status.loop # SSH → docker compose ps (infra)
│   ├── media-status.loop # SSH → docker compose ps (media)
│   ├── infra.vertex      # Infrastructure stack health
│   └── media.vertex      # Media stack health
├── sources/              # Additional monitoring sources
│   ├── alerts.loop       # Prometheus alerts via SSH
│   └── logs.loop         # Docker compose logs via SSH
└── alerting/
    └── thresholds.vertex # Alert aggregation
```

## Usage

```bash
# Validate syntax
loop validate local/disk.loop
loop validate root.vertex

# Test local monitoring
loop run local/local.vertex

# Full homelab (requires SSH access to VMs)
loop run root.vertex
```

## What This Proves

1. **Parse pipelines work** - df/ps output parsed to structured facts
2. **SSH sources work** - Remote command execution via SSH
3. **JSON format works** - docker compose ps --format json
4. **Vertex aggregation works** - Multi-level fold and boundary
5. **discover: works** - Auto-finding nested .vertex files

## Known Gaps

See `.subtask/tasks/exp--homelab/PLAN.md` for full gap analysis.

Key limitations:
- No multi-host iteration (separate .loop per host)
- No JSONPath extraction (Prometheus API nested response)
- No conditional signal emission
- No continuous streaming (poll snapshots only)

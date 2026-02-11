# Prometheus Alerts → Loops Data Stream

Status: **Percolating** — design direction, not committed work.

## Context

The gruel.network homelab runs a full Prometheus + Loki + Grafana monitoring
stack on the infra VM (192.168.1.30). Prometheus scrapes node-exporters and
service exporters across all hosts every 15 seconds, evaluates alert rules,
and stores 30 days of time-series data. Grafana provides dashboards.

**The problem:** Nobody opens Grafana. The dashboards exist but aren't part of
any natural workflow. Meanwhile, loops is being built as the household's
primary data stream — RSS, HN, Bluesky, and eventually more. Alerts about
infrastructure should surface where attention already lives.

## The Idea

Keep Prometheus as the collection and alerting engine. Drop Grafana. Route
Prometheus alerts into loops as just another source in the data stream.

```
Prometheus (keep)              Loops (surface layer)
  │                               │
  ├── scrapes metrics             ├── RSS feeds
  ├── evaluates alert rules       ├── HN
  ├── fires alerts ──────────────▶├── Bluesky
  │                               ├── infrastructure alerts ← this
  └── TSDB stays for ad-hoc      └── unified household stream
      PromQL queries
```

Infrastructure alerts become items alongside reading material. "Family VM
disk at 85%" sits next to a blog post. Triage happens in one place.

## What Prometheus Is Good At (Keep)

- **Pull-based scraping** — the act of collecting is the health check
- **TSDB** — extremely efficient compression, 160 MB for 30 days across 10+ hosts
- **PromQL** — rate calculations, predictions, cross-host joins
- **Exporter ecosystem** — node-exporter, exportarr, jellyfin-exporter all speak its format natively
- **Alert rule evaluation** — `for: 5m` debouncing, `predict_linear()` for trend alerts

Resource cost: ~160 MB RSS, 0.3% CPU. Lightweight enough to keep forever.

## What Gets Dropped (Grafana)

Grafana costs ~175 MB RSS and 0.6% CPU for dashboards nobody opens. The
Prometheus expression browser (`prometheus.gruel.network`) and direct API
queries (`/api/v1/query`) remain available for ad-hoc deep dives.

Loki stays — log aggregation is valuable independent of the visualization
layer. LogQL queries work via API too.

## Integration Points

### Option A: Poll Prometheus API

hlab already has `.loop` files that query Prometheus:

```
apps/hlab/src/hlab/loops/prometheus/
├── alerts.loop      # /api/v1/alerts
├── rules.loop       # /api/v1/rules
└── targets.loop     # /api/v1/targets
```

A loops source could poll `/api/v1/alerts` on a cadence and emit firing
alerts as Facts. This is the simplest path — no new infrastructure, just
another source definition. hlab's `alerts` command already does this for
CLI display.

### Option B: Alertmanager Webhook

Prometheus can POST alert payloads to a webhook when alerts fire/resolve.
A loops webhook receiver would convert these to Facts in real-time. Lower
latency than polling, but requires a persistent listener endpoint.

### Option C: Hybrid

Poll for current state on loops startup, webhook for real-time transitions.
This is probably overkill for a homelab.

**Recommendation:** Option A. Poll the API. It's already proven in hlab's
alerts command, requires no new infrastructure, and the latency of a 30-60s
poll interval is fine for homelab alerts.

## Fact Shape

```python
Fact(
    kind="infra.alert",
    ts=alert_fired_at,
    observer="prometheus",
    payload={
        "name": "HighMemoryUsage",
        "severity": "warning",
        "instance": "family",
        "summary": "family memory above 90%",
        "state": "firing",         # or "resolved"
        "duration": "5m",          # how long it's been firing
        "value": 0.92,             # current metric value
    }
)
```

## What This Enables

- Infrastructure alerts in the same stream as everything else
- Alert history as Facts in the store (when did this last fire?)
- Fold/boundary logic for alert fatigue (suppress repeated firings, surface escalations)
- Eventually: Loki log snippets attached to alerts for context

## Current gruel.network Monitoring Coverage

As of 2026-02-11:

| Host | Node Exporter | Promtail | Prometheus Scrape |
|------|:---:|:---:|:---:|
| infra (.30) | ✅ | ✅ | ✅ |
| media (.40) | ✅ | ✅ | ✅ |
| dev (.41) | ✅ | ✅ | ✅ |
| runner-01 (.50) | ✅ | ✅ | ✅ |
| runner-02 (.51) | ✅ | ✅ | ✅ |
| pve-nas (.11) | ✅ | — | ✅ |
| grove (.43) | ✅ | ✅ | ✅ |
| family (.45) | ✅ | ✅ | ✅ |
| inference (.46) | ✅ | ✅ | ✅ |
| alcove (.44) | ✅ | — (no Docker) | ✅ |

## Open Questions

- What alert rules matter for the household stream vs. ops-only?
- Should resolved alerts appear as items or just silently clear?
- Does Uptime Kuma stay (synthetic probing) or fold into this too?
- Severity → visual treatment mapping in cells

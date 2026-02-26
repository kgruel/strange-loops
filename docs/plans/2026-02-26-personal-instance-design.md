# Personal Instance Design

## Context

The `loops init` + recursive source collection features are in place. This
design covers setting up `~/.config/loops/` as a personal instance with
multiple domains discovered by a single root vertex.

## Structure

```
~/.config/loops/
├── root.vertex                    # discovers all *.vertex below
│
├── reading/                       # attention: feeds + reactions
│   ├── reading.vertex
│   ├── feeds.list
│   ├── sources/feed.loop
│   └── data/
│
├── economy/                       # macro indicators: FRED + Redfin bulk
│   ├── economy.vertex
│   ├── series.list                # FRED series codes
│   ├── sources/
│   │   ├── fred.loop              # FRED API template
│   │   └── redfin.loop            # Redfin Data Center CSV pull
│   └── data/
│
├── realestate/                    # property-specific tracking (stub)
├── system/                        # local machine monitoring (stub)
├── homelab/                       # per-VM agent pattern (stub)
└── ambient/                       # browsing history, attention traces (stub)
```

**Convention:** `<domain>/<domain>.vertex` + `sources/` + `data/`.

## Domains Wired Today

### Reading

Consolidate demo/feeds.vertex + demo/reactions.vertex into one reading.vertex.
Same source template (feed.loop), same fold shape. Two stores collapse to one.

### Economy

Two source patterns:

1. **FRED API** — template `fred.loop` instantiated per series from `series.list`.
   API key via `FRED_API_KEY` env var. Returns JSON observations.
   Initial series: federal funds rate, CPI, unemployment, 30yr mortgage, housing starts.

2. **Redfin Data Center** — bulk CSV download. Longer cadence (daily/weekly).
   Stub source, wire with real URL once geography is chosen.

## Domains Stubbed

realestate, system, homelab, ambient — directory structure + stub vertex only.
Discovered by root but inert (no sources, no facts).

## Future Work

- `.vars` file convention for per-domain configuration
- Per-VM homelab agent pattern
- Safari history → ambient attention traces
- Redfin CSV geography selection
- Property-specific tracking via scrape

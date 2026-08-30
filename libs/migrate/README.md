# `migrate` — Migration Sidecar

The `migrate` package provides a migration sidecar for transforming pre-Arrival legacy stores into Arrival lineages. Under the quarantine architecture, no active runtime package may import `migrate`, isolating historical format knowledge and legacy codecs from the 1.0 runtime. For full design specifications and protocol obligations, see `docs/scratch/arrival-break/slice4-design-proposal.md` and design fact `design:arrival-break-slice4-migration-sidecar`.

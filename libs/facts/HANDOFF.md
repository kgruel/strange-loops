# facts — Handoff

## 2026-01-26
Clean break: Event -> Fact. Stripped CLI output framework (Event, Result,
Emitter, ListEmitter, NullEmitter, JsonEmitter, PlainEmitter). 6,081 lines
removed. Fact is the observation atom: `Fact(kind: str, ts: datetime,
payload: T)`. Factory: `Fact.of("heartbeat", service="api")`. Dict payloads
wrapped in MappingProxyType. Serialization via to_dict/from_dict.

Build backend switched from uv_build to hatchling (aligning with all other
libs). Version reset from 1.0.0 to 0.1.0.

## 2026-01-27
Added `Fact.tick(name, **data)` classmethod — convenience factory for
boundary-related facts. Auto-prefixes kind to `tick.{name}`, following the
infrastructure namespacing convention (`tick.` prefix parallels `ui.` prefix
from cells). Same semantics as `Fact.of()`: epoch float ts, dict payload
wrapped in MappingProxyType.

## Open
- **Kind conventions**: Open string by design. Review as usage patterns emerge.

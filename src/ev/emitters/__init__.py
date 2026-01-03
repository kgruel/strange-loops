"""Reference emitters for ev.

Core emitters (no dependencies):
    - JsonEmitter: Machine-readable JSON output
    - PlainEmitter: Minimal text output

Optional emitters (require extras):
    - RichEmitter: Beautiful terminal output (requires 'rich')
"""

from ev.emitters.json import JsonEmitter
from ev.emitters.plain import PlainEmitter

__all__ = [
    "JsonEmitter",
    "PlainEmitter",
]

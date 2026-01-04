"""Reference emitters for ev.

Core emitters (no dependencies):
    - JsonEmitter: Machine-readable JSON output
    - PlainEmitter: Minimal text output
    - FileEmitter: JSONL file output for debugging
    - TeeEmitter: Forward to multiple emitters

Optional emitters (require extras):
    - RichEmitter: Beautiful terminal output (requires 'rich')
"""

from ev.emitters.json import JsonEmitter
from ev.emitters.plain import PlainEmitter
from ev.emitters.tee import FileEmitter, TeeEmitter

__all__ = [
    "FileEmitter",
    "JsonEmitter",
    "PlainEmitter",
    "TeeEmitter",
]

"""Reference emitters for facts.

Core emitters (no dependencies):
    - JsonEmitter: Machine-readable JSON output
    - PlainEmitter: Minimal text output
"""

from facts.emitters.json import JsonEmitter
from facts.emitters.plain import PlainEmitter

__all__ = [
    "JsonEmitter",
    "PlainEmitter",
]

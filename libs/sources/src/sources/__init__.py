"""Sources: adapters from the external world into Vertex.

Infrastructure at the ingress boundary — converts external signals
(commands, files, network events) into Facts that flow into Vertex.
Not atoms — sources don't appear in the fundamental model.
"""

from .protocol import SourceProtocol
from .runner import Runner
from .source import CommandSource, Source

__all__ = ["Source", "SourceProtocol", "CommandSource", "Runner"]

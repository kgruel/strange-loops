"""Sources: adapters from the external world into Vertex.

Infrastructure at the ingress boundary — converts external signals
(commands, files, network events) into Facts that flow into Vertex.
Not atoms — sources don't appear in the fundamental model.
"""

from .command import CommandSource
from .protocol import Source
from .runner import Runner

__all__ = ["Source", "CommandSource", "Runner"]

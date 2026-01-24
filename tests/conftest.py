"""Test configuration: allow importing render submodules without full package init."""

import importlib
import sys
from types import ModuleType
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Pre-register the render package as a namespace so submodule imports
# don't trigger render/__init__.py (which pulls in heavy dependencies).
if "render" not in sys.modules:
    pkg = ModuleType("render")
    pkg.__path__ = [str(Path(__file__).resolve().parent.parent / "render")]
    pkg.__package__ = "render"
    sys.modules["render"] = pkg

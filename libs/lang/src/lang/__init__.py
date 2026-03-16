"""KDL-based loader for .loop and .vertex files.

Uses lazy imports via __getattr__ so that importing a single symbol
(e.g. ``from lang import parse_vertex_file``) doesn't load the entire AST.
"""

# Eagerly import only the loader (lightweight after ast.py optimization)
from .loader import parse_loop, parse_loop_file, parse_vertex, parse_vertex_file
# validator deferred — imported on first access via __getattr__

__all__ = [
    # AST types - Loop file
    "LoopFile",
    "Duration",
    "ParseStep",
    "Skip",
    "Split",
    "Pick",
    "Transform",
    "TransformOp",
    "Strip",
    "LStrip",
    "RStrip",
    "Replace",
    "Coerce",
    "Trigger",
    "Explode",
    "Project",
    "Where",
    "Flatten",
    # AST types - Vertex file
    "VertexFile",
    "LoopDef",
    "FoldDecl",
    "FoldOp",
    "FoldAvg",
    "FoldBy",
    "FoldCollect",
    "FoldCount",
    "FoldLatest",
    "FoldMax",
    "FoldMin",
    "FoldSum",
    "FoldWindow",
    "Boundary",
    "BoundaryAfter",
    "BoundaryCondition",
    "BoundaryEvery",
    "BoundaryWhen",
    # AST types - Combinatorial vertices
    "CombineEntry",
    # AST types - Lens declarations
    "LensDecl",
    # AST types - Observer declarations
    "ObserverDecl",
    "GrantDecl",
    # AST types - Inline sources / sources blocks
    "InlineSource",
    "SourcesBlock",
    # AST types - Template sources
    "SourceEntry",
    "SourceParams",
    "TemplateSource",
    "FromFile",
    "FromSource",
    # Parser (KDL loader)
    "parse_loop",
    "parse_loop_file",
    "parse_vertex",
    "parse_vertex_file",
    # Errors
    "DSLError",
    "LexError",
    "ParseError",
    "ValidationError",
    "Location",
    # Population management
    "PopulationRow",
    "PopulationInfo",
    "resolve_vertex",
    "resolve_template",
    "template_name",
    "read_population",
    # Validator
    "validate",
    "validate_loop",
    "validate_vertex",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {}

# AST types
_AST_NAMES = [
    "Boundary", "BoundaryAfter", "BoundaryCondition", "BoundaryEvery", "BoundaryWhen",
    "Coerce", "CombineEntry", "Duration", "Explode", "Flatten",
    "FoldAvg", "FoldBy", "FoldCollect", "FoldCount", "FoldDecl", "FoldLatest",
    "FoldMax", "FoldMin", "FoldOp", "FoldSum", "FoldWindow",
    "FromFile", "FromSource", "GrantDecl", "InlineSource", "LensDecl",
    "LoopDef", "LoopFile", "LStrip", "ObserverDecl", "ParseStep",
    "Pick", "Project", "Replace", "RStrip", "Skip",
    "SourceEntry", "SourceParams", "SourcesBlock", "Split", "Strip",
    "TemplateSource", "Transform", "TransformOp", "Trigger", "VertexFile", "Where",
]
for _n in _AST_NAMES:
    _LAZY_IMPORTS[_n] = ("lang.ast", _n)

# Errors
for _n in ["DSLError", "LexError", "Location", "ParseError", "ValidationError"]:
    _LAZY_IMPORTS[_n] = ("lang.errors", _n)

# Population
for _n in ["PopulationInfo", "PopulationRow", "read_population", "resolve_template", "resolve_vertex", "template_name"]:
    _LAZY_IMPORTS[_n] = ("lang.population", _n)

# Validator
for _n in ["validate", "validate_loop", "validate_vertex"]:
    _LAZY_IMPORTS[_n] = ("lang.validator", _n)


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        import importlib
        module = importlib.import_module(module_path)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'lang' has no attribute {name!r}")

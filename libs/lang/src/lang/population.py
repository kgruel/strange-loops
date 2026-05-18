"""Population management for template sources.

Read, write, and transform template populations in .vertex files.
Populations are the parameter rows that instantiate a .loop template N times.
"""

from __future__ import annotations

# re deferred to function bodies (avoids enum ~5ms import)
from typing import TYPE_CHECKING

from .ast import FromFile, SourceParams, TemplateSource, VertexFile

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class PopulationRow:
    """One row in a template population."""

    __slots__ = ("key", "values")

    def __init__(self, key: str, values: dict[str, str]):
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "values", values)

    def __repr__(self):
        return f"PopulationRow(key={self.key!r}, values={self.values!r})"

    def __eq__(self, other):
        if type(self) is not type(other):
            return NotImplemented
        return (self.key, self.values) == (other.key, other.values)

    def __setattr__(self, name, value):
        raise AttributeError(f"cannot assign to field '{name}'")

    def __delattr__(self, name):
        raise AttributeError(f"cannot delete field '{name}'")


class PopulationInfo:
    """Complete population for a template source."""

    __slots__ = ("template_name", "header", "rows", "storage", "file_path", "vertex_path")

    def __init__(self, template_name: str, header: list[str], rows: list[PopulationRow],
                 storage: str, file_path: Path | None, vertex_path: Path):
        object.__setattr__(self, "template_name", template_name)
        object.__setattr__(self, "header", header)
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "storage", storage)
        object.__setattr__(self, "file_path", file_path)
        object.__setattr__(self, "vertex_path", vertex_path)

    def __repr__(self):
        return (f"PopulationInfo(template_name={self.template_name!r}, "
                f"header={self.header!r}, rows={self.rows!r}, "
                f"storage={self.storage!r}, file_path={self.file_path!r}, "
                f"vertex_path={self.vertex_path!r})")

    def __eq__(self, other):
        if type(self) is not type(other):
            return NotImplemented
        return all(getattr(self, f) == getattr(other, f) for f in self.__slots__)

    def __setattr__(self, name, value):
        raise AttributeError(f"cannot assign to field '{name}'")

    def __delattr__(self, name):
        raise AttributeError(f"cannot delete field '{name}'")


# ---------------------------------------------------------------------------
# Vertex + template resolution
# ---------------------------------------------------------------------------


def resolve_vertex(name_or_path: str, home: Path) -> Path:
    """Name or path -> .vertex file path.

    - Has .vertex extension -> use as-is
    - Starts with . or / -> use as-is (filesystem path)
    - Otherwise -> home / name / name.vertex
    """
    from pathlib import Path
    if (
        name_or_path.endswith(".vertex")
        or name_or_path.startswith("./")
        or name_or_path.startswith("/")
    ):
        return Path(name_or_path)
    return home / name_or_path / f"{Path(name_or_path).name}.vertex"


def template_name(ts: TemplateSource) -> str:
    """TemplateSource -> stem of .loop path (e.g., 'feed', 'fred')."""
    return ts.template.stem


def resolve_template(vertex: VertexFile, qualifier: str | None) -> TemplateSource:
    """Find target template source.

    Single template -> qualifier optional.
    Multiple -> qualifier required, matched against .loop stem.
    When no qualifier and multiple templates share a stem, prefers the
    file-backed template (the growable population) over inline-only ones.
    Raises ValueError with helpful message listing available templates.
    """
    templates = [
        s for s in (vertex.sources or ()) if isinstance(s, TemplateSource)
    ]

    if not templates:
        raise ValueError(f"Vertex '{vertex.name}' has no template sources")

    if len(templates) == 1 and qualifier is None:
        return templates[0]

    if qualifier is not None:
        matches = [t for t in templates if template_name(t) == qualifier]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            # Multiple templates with same stem — prefer file-backed
            file_backed = [t for t in matches if t.from_ is not None]
            if len(file_backed) == 1:
                return file_backed[0]
            raise ValueError(
                f"Multiple templates named '{qualifier}' in vertex "
                f"'{vertex.name}'. Cannot disambiguate."
            )
        names = [template_name(t) for t in templates]
        raise ValueError(
            f"No template '{qualifier}' in vertex '{vertex.name}'. "
            f"Available: {', '.join(names)}"
        )

    # No qualifier — check for unique stems
    names = [template_name(t) for t in templates]
    unique_names = set(names)
    if len(unique_names) == 1:
        # All templates share same stem — prefer file-backed
        file_backed = [t for t in templates if t.from_ is not None]
        if len(file_backed) == 1:
            return file_backed[0]

    raise ValueError(
        f"Vertex '{vertex.name}' has {len(templates)} templates: "
        f"{', '.join(names)}. Specify one with vertex/template."
    )


# ---------------------------------------------------------------------------
# .list file operations
# ---------------------------------------------------------------------------


def list_file_read(path: Path) -> tuple[list[str], list[PopulationRow]]:
    """Read header + rows from a .list file.

    Skips comments (#) and blank lines.
    Last column gets remainder (split limit = len(header) - 1).
    """
    text = path.read_text()
    lines = text.splitlines()
    header: list[str] | None = None
    rows: list[PopulationRow] = []

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        if header is None:
            header = line.split()
            continue

        parts = line.split(None, len(header) - 1)
        if len(parts) != len(header):
            continue  # skip malformed rows
        values = dict(zip(header, parts))
        rows.append(PopulationRow(key=parts[0], values=values))

    return header or [], rows


def list_file_header(path: Path) -> list[str]:
    """Read only the header row from a .list file.

    Returns [] if no header is present.
    """
    if not path.exists():
        return []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        return line.split()
    return []


def list_file_add(path: Path, header: list[str], row: PopulationRow) -> None:
    """Append row to .list file. Creates file with header if it doesn't exist."""
    if not path.exists():
        path.write_text(
            " ".join(header)
            + "\n"
            + " ".join(row.values[h] for h in header)
            + "\n"
        )
        return

    with open(path, "a") as f:
        f.write(" ".join(row.values[h] for h in header) + "\n")


def list_file_rm(path: Path, key: str) -> bool:
    """Remove row by key (first column). Returns True if found.

    Preserves header, comments, and blank lines.
    """
    if not path.exists():
        return False

    lines = path.read_text().splitlines()
    kept: list[str] = []
    removed = False
    header_seen = False

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            if not header_seen:
                # First non-comment, non-blank line is the header — always keep
                header_seen = True
                kept.append(line)
                continue
            parts = stripped.split(None, 1)
            if parts and parts[0] == key:
                removed = True
                continue
        kept.append(line)

    if removed:
        path.write_text("\n".join(kept) + "\n")
    return removed


def list_file_write(path: Path, header: list[str], rows: list[PopulationRow]) -> None:
    """Full rewrite of a .list file."""
    lines = [" ".join(header)]
    for row in rows:
        lines.append(" ".join(row.values[h] for h in header))
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Population reading
# ---------------------------------------------------------------------------


def read_population(
    vertex: VertexFile, template: TemplateSource, base_dir: Path
) -> PopulationInfo:
    """Read full population — merges file rows + inline rows.

    Header inferred from first available row's keys.
    """
    file_rows: list[PopulationRow] = []
    file_header: list[str] = []
    file_path: Path | None = None

    # File-sourced rows
    if isinstance(template.from_, FromFile):
        fp = template.from_.path
        if not fp.is_absolute():
            fp = base_dir / fp
        file_path = fp
        if fp.exists():
            file_header, file_rows = list_file_read(fp)

    # Inline rows
    inline_rows: list[PopulationRow] = []
    for sp in template.params:
        key = next(iter(sp.values.values())) if sp.values else ""
        inline_rows.append(PopulationRow(key=key, values=dict(sp.values)))

    # Determine storage
    has_file = template.from_ is not None
    has_inline = len(template.params) > 0
    if has_file and has_inline:
        storage = "both"
    elif has_file:
        storage = "file"
    else:
        storage = "inline"

    # Merge rows: file first, then inline
    all_rows = file_rows + inline_rows

    # Infer header
    if file_header:
        header = file_header
    elif all_rows:
        header = list(all_rows[0].values.keys())
    else:
        header = []

    return PopulationInfo(
        template_name=template_name(template),
        header=header,
        rows=all_rows,
        storage=storage,
        file_path=file_path,
        vertex_path=vertex.path or base_dir,
    )


# ---------------------------------------------------------------------------
# KDL text manipulation — generic path-parametric splice
# ---------------------------------------------------------------------------
#
# Path encoding (list[str]): each entry is the stripped-line header of a
# block, optionally including its first quoted positional arg.
#
#   ["loops"]                          → matches `loops { ... }`
#   ["loops", "decision"]              → `decision { ... }` inside loops
#   ['template "feed.loop"']           → top-level `template "feed.loop" { ... }`
#   ['sources', 'template "feed.loop"']→ template inside a sources block
#   ['combine', 'vertex "./foo.vertex"'] → vertex entry inside combine
#
# Quoted-arg matching uses Path() equality so ./feed.loop == feed.loop.
# Bare-name segments match the first token only — fine for singleton parents
# (loops, observers, combine, lens, sources) which is the corpus reality.


def _parse_segment(segment: str) -> tuple[str, str | None]:
    """Parse a path segment into (name, optional_quoted_key).

    'loops'                   -> ('loops', None)
    'template "feed.loop"'    -> ('template', 'feed.loop')
    'vertex "./project.vertex"' -> ('vertex', './project.vertex')
    """
    import re
    m = re.match(r'^(\S+)(?:\s+"([^"]+)")?\s*$', segment)
    if not m:
        raise ValueError(f"Invalid path segment: {segment!r}")
    return m.group(1), m.group(2)


def _line_opens_matching_block(stripped: str, segment: str) -> bool:
    """True iff `stripped` is the opening line of a block matching `segment`."""
    if "{" not in stripped:
        return False
    name, key = _parse_segment(segment)
    if not stripped.startswith(name):
        return False
    # Ensure name is a complete token, not a prefix (e.g. 'loops' should not
    # match 'loopstest'). The next char must be space, brace, or quote.
    nxt = stripped[len(name) : len(name) + 1]
    if nxt and nxt not in (" ", "{", '"', "\t"):
        return False
    if key is None:
        return True
    import re
    m = re.search(r'"([^"]+)"', stripped)
    if not m:
        return False
    from pathlib import Path
    return Path(m.group(1)) == Path(key)


def _line_matches_child(
    stripped: str,
    child_name: str,
    child_key: str | None = None,
    key_field: str | None = None,
) -> bool:
    """Match a child line by name + optional discriminator.

    - name only: first token equals child_name
    - + child_key (no key_field): match first quoted positional arg via Path()
    - + child_key + key_field: match `key_field="child_key"` property substring
    """
    if not stripped.startswith(child_name):
        return False
    nxt = stripped[len(child_name) : len(child_name) + 1]
    if nxt and nxt not in (" ", "{", '"', "\t"):
        return False
    if child_key is None:
        return True
    if key_field is not None:
        return f'{key_field}="{child_key}"' in stripped
    # Positional first-quoted-arg match (Path-style)
    import re
    m = re.search(r'"([^"]+)"', stripped)
    if not m:
        return False
    from pathlib import Path
    return Path(m.group(1)) == Path(child_key)


def kdl_find_block(text: str, path: list[str]) -> tuple[int, int]:
    """Locate a nested block by path. Returns (start_line_idx, end_line_idx) inclusive.

    Each path segment is `'name'` for a bare-name block, or `'name "key"'` for
    a block discriminated by its first quoted positional arg. Walks brace
    depth to scope each segment's search to its parent's body.

    Raises ValueError on missing or unclosed blocks.
    """
    if not path:
        raise ValueError("path must contain at least one segment")
    lines = text.splitlines()
    # Search window: full file for first segment, then narrows.
    search_start = 0
    search_end = len(lines) - 1
    block_start = -1
    block_end = -1

    for seg_idx, segment in enumerate(path):
        block_start, block_end = _scan_block(
            lines, search_start, search_end, segment
        )
        # Next segment searches strictly inside this block's body.
        search_start = block_start + 1
        search_end = block_end - 1
        # If we're at the last segment, we're done.
        if seg_idx == len(path) - 1:
            return block_start, block_end

    # Unreachable — loop always returns inside.
    raise ValueError(f"Block not found for path {path!r}")


def _scan_block(
    lines: list[str], lo: int, hi: int, segment: str
) -> tuple[int, int]:
    """Scan lines[lo..hi] for a block matching segment. Brace-depth tracked.

    Skips over nested children at depth>0 so we only match siblings of the
    target's scope. Returns (start_line, end_line) inclusive.
    """
    start = -1
    depth = 0
    i = lo
    while i <= hi:
        stripped = lines[i].strip()
        if start == -1:
            # Only consider lines at depth 0 (sibling scope) as potential matches.
            if _line_opens_matching_block(stripped, segment):
                start = i
                depth = stripped.count("{") - stripped.count("}")
                if depth == 0:
                    return start, i
            else:
                # Track depth changes from non-matching opens so we skip their bodies.
                opens = stripped.count("{")
                closes = stripped.count("}")
                if opens > closes:
                    # Skip this nested block's body entirely.
                    body_depth = opens - closes
                    j = i + 1
                    while j <= hi and body_depth > 0:
                        body_depth += lines[j].count("{") - lines[j].count("}")
                        j += 1
                    i = j
                    continue
        else:
            depth += stripped.count("{") - stripped.count("}")
            if depth <= 0:
                return start, i
        i += 1

    if start != -1:
        raise ValueError(f"Unclosed block for segment {segment!r}")
    raise ValueError(f"Block not found for segment {segment!r}")


def _detect_indent(lines: list[str], start: int, end: int) -> str:
    """Detect indentation of children within a block."""
    for i in range(start + 1, end + 1):
        stripped = lines[i].strip()
        if stripped and stripped != "}":
            return lines[i][: len(lines[i]) - len(lines[i].lstrip())]
    # Fallback: parent line indent + 2 spaces
    parent_indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
    return parent_indent + "  "


def kdl_insert_child(
    text: str,
    parent_path: list[str],
    child_text: str,
) -> str:
    """Insert child_text into the block at parent_path.

    Placement rule: after the last existing sibling whose first token matches
    the first token of child_text (preserves authorial grouping). If no such
    sibling exists, insert just before the parent's closing brace.

    child_text may be multi-line. Leading common whitespace is stripped, then
    each line is re-indented to match the parent's child-indent.
    """
    if not child_text.strip():
        raise ValueError("child_text is empty")
    had_trailing = text.endswith("\n")
    lines = text.splitlines()
    start, end = kdl_find_block(text, parent_path)
    indent = _detect_indent(lines, start, end)

    # Normalize child_text: dedent + strip outer blank lines.
    from textwrap import dedent
    body = dedent(child_text).strip("\n")
    child_lines = [
        (indent + ln) if ln.strip() else ln  # don't indent blank lines
        for ln in body.splitlines()
    ]
    # First token of child for sibling-grouping placement.
    child_first = child_lines[0].strip().split(None, 1)[0]

    # Find insertion point: after last sibling-of-same-first-token at depth 0
    # inside the block, else just before the closing brace.
    insert_at = end  # default: line where closing '}' lives — insert before it
    depth = 0
    for i in range(start + 1, end):
        stripped = lines[i].strip()
        if depth == 0:
            tok = stripped.split(None, 1)[0] if stripped else ""
            # Strip any leading '/' (e.g. // comments) so comments don't match.
            if tok and tok == child_first:
                # Determine where this sibling ends — could be single-line or
                # span a block.
                sib_open = lines[i].count("{") - lines[i].count("}")
                if sib_open == 0:
                    insert_at = i + 1
                else:
                    # Walk to matching close.
                    d = sib_open
                    j = i + 1
                    while j < end and d > 0:
                        d += lines[j].count("{") - lines[j].count("}")
                        j += 1
                    insert_at = j
        depth += lines[i].count("{") - lines[i].count("}")

    # Special case: parent block is single-line `name { ... }` — split it.
    if start == end:
        # Convert single-line block into multi-line and place child inside.
        # We re-emit the line as: <opening>\n<child>\n<closing>
        line = lines[start]
        # Find first '{' and last '}'.
        open_idx = line.index("{")
        close_idx = line.rindex("}")
        opening = line[: open_idx + 1].rstrip()
        inner = line[open_idx + 1 : close_idx].strip()
        closing_indent = line[: len(line) - len(line.lstrip())]
        closing = closing_indent + "}"
        child_indent = closing_indent + "  "
        new_lines = [opening]
        if inner:
            new_lines.append(child_indent + inner)
        new_lines.extend(
            (child_indent + ln) if ln.strip() else ln
            for ln in body.splitlines()
        )
        new_lines.append(closing)
        lines[start : end + 1] = new_lines
    else:
        for offset, ln in enumerate(child_lines):
            lines.insert(insert_at + offset, ln)

    result = "\n".join(lines)
    if had_trailing:
        result += "\n"
    return result


def kdl_remove_child(
    text: str,
    parent_path: list[str],
    child_name: str,
    child_key: str | None = None,
    key_field: str | None = None,
) -> str:
    """Remove a child from the block at parent_path.

    Matching modes:
    - child_name only: removes first child whose first token is child_name
    - + child_key (no key_field): match first quoted positional arg
    - + child_key + key_field: match `key_field="child_key"` property

    Removes the entire child span (single-line or multi-line block).
    Raises ValueError if no matching child found.

    Limitation: when the parent block is itself single-line
    (``loops { decision { ... } }`` rendered on one line), there are no
    child *lines* to scan and removal will raise "No matching child".
    Use ``kdl_insert_child`` first to expand the parent across lines if
    you need to mutate single-line parents.
    """
    had_trailing = text.endswith("\n")
    lines = text.splitlines()
    start, end = kdl_find_block(text, parent_path)

    # Walk children at depth 0 inside the block.
    depth = 0
    i = start + 1
    while i < end:
        stripped = lines[i].strip()
        if depth == 0 and _line_matches_child(stripped, child_name, child_key, key_field):
            opens = lines[i].count("{") - lines[i].count("}")
            if opens == 0:
                # Single-line: remove this one line.
                del lines[i]
            else:
                # Multi-line block child: walk to matching close.
                d = opens
                j = i + 1
                while j < end and d > 0:
                    d += lines[j].count("{") - lines[j].count("}")
                    j += 1
                del lines[i:j]
            result = "\n".join(lines)
            if had_trailing:
                result += "\n"
            return result
        depth += lines[i].count("{") - lines[i].count("}")
        i += 1

    desc = (
        f"{child_name}"
        + (f" {key_field}={child_key!r}" if key_field else f' "{child_key}"' if child_key else "")
    )
    raise ValueError(
        f"No matching child '{desc}' inside parent path {parent_path!r}"
    )


# ---------------------------------------------------------------------------
# Back-compat wrappers — old surface, new internals
# ---------------------------------------------------------------------------


def _template_parent_path(text: str, template_path_str: str) -> list[str]:
    """Resolve the parent_path that contains a template block.

    Returns [] for top-level templates, ['sources'] for templates inside a
    sources block. The corpus has only these two placements.
    """
    seg = f'template "{template_path_str}"'
    try:
        kdl_find_block(text, [seg])
        return []
    except ValueError as exc:
        # "Unclosed" means the opening was found but didn't terminate — no point
        # trying sources fallback. "Block not found" means the segment is absent
        # at this scope; try the next.
        if "Unclosed" in str(exc):
            raise ValueError(
                f"Unclosed template block for {template_path_str}"
            ) from exc
    try:
        kdl_find_block(text, ["sources", seg])
        return ["sources"]
    except ValueError as exc:
        if "Unclosed" in str(exc):
            raise ValueError(
                f"Unclosed template block for {template_path_str}"
            ) from exc
        raise ValueError(
            f"Template block not found for {template_path_str}"
        ) from exc


def _find_template_block(
    lines: list[str], template_path_str: str
) -> tuple[int, int]:
    """[back-compat] Find template block by quoted path arg.

    Looks at top-level first, then inside `sources { ... }`. Wraps errors
    with the legacy 'Template block not found' / 'Unclosed template block'
    message shape so existing callers and tests don't break.
    """
    text = "\n".join(lines)
    parent = _template_parent_path(text, template_path_str)
    seg = f'template "{template_path_str}"'
    return kdl_find_block(text, [*parent, seg])


def kdl_insert_with_row(
    text: str, template_path_str: str, values: dict[str, str]
) -> str:
    """Insert a 'with' line into a template block.

    Inserts after the last existing 'with' or 'from' line, or at end of block.
    """
    had_trailing = text.endswith("\n")
    lines = text.splitlines()
    start, end = _find_template_block(lines, template_path_str)
    indent = _detect_indent(lines, start, end)

    # Find insertion point: after last with/from at depth 0, else start+1.
    insert_at = start + 1
    depth = 0
    for i in range(start + 1, end):
        stripped = lines[i].strip()
        if depth == 0 and (
            stripped.startswith("with ") or stripped.startswith("from ")
        ):
            insert_at = i + 1
            indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
        depth += lines[i].count("{") - lines[i].count("}")

    props = " ".join(f'{k}="{v}"' for k, v in values.items())
    lines.insert(insert_at, f"{indent}with {props}")
    result = "\n".join(lines)
    if had_trailing:
        result += "\n"
    return result


def kdl_remove_with_row(
    text: str, template_path_str: str, key_field: str, key_value: str
) -> str:
    """Remove the 'with' row where key_field matches key_value."""
    parent = _template_parent_path(text, template_path_str)
    try:
        return kdl_remove_child(
            text,
            [*parent, f'template "{template_path_str}"'],
            "with",
            key_value,
            key_field=key_field,
        )
    except ValueError as exc:
        # Preserve back-compat error message shape.
        raise ValueError(
            f"No with row matching {key_field}={key_value!r}"
        ) from exc


# ---------------------------------------------------------------------------
# Representation transforms
# ---------------------------------------------------------------------------


def export_to_file(
    vertex_text: str, template_path_str: str, from_file_ref: str
) -> str:
    """Remove inline with rows, add 'from file' directive.

    Returns modified KDL text. Caller is responsible for writing the .list file.
    """
    had_trailing = vertex_text.endswith("\n")
    lines = vertex_text.splitlines()
    start, end = _find_template_block(lines, template_path_str)

    indent = _detect_indent(lines, start, end)

    # Remove with lines (reverse order to preserve indices)
    to_remove = []
    for i in range(start + 1, end + 1):
        if lines[i].strip().startswith("with "):
            to_remove.append(i)
    for i in reversed(to_remove):
        lines.pop(i)

    # Re-find block (indices shifted)
    start, end = _find_template_block(lines, template_path_str)

    # Add from file if not present
    has_from = any(
        lines[i].strip().startswith("from ")
        for i in range(start + 1, end + 1)
    )
    if not has_from:
        lines.insert(start + 1, f'{indent}from file "{from_file_ref}"')

    result = "\n".join(lines)
    if had_trailing:
        result += "\n"
    return result


def import_from_file(
    vertex_text: str, template_path_str: str, rows: list[PopulationRow]
) -> str:
    """Remove 'from file' line, insert with rows.

    Returns modified KDL text.
    """
    had_trailing = vertex_text.endswith("\n")
    lines = vertex_text.splitlines()
    start, end = _find_template_block(lines, template_path_str)

    indent = _detect_indent(lines, start, end)

    # Remove from file line
    for i in range(start + 1, end + 1):
        if lines[i].strip().startswith("from "):
            lines.pop(i)
            break

    # Re-find block
    start, end = _find_template_block(lines, template_path_str)

    # Insert with rows after template opening
    insert_at = start + 1
    for row in rows:
        props = " ".join(f'{k}="{v}"' for k, v in row.values.items())
        lines.insert(insert_at, f"{indent}with {props}")
        insert_at += 1

    result = "\n".join(lines)
    if had_trailing:
        result += "\n"
    return result

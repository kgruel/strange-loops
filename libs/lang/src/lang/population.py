"""Population management for template sources.

Read, write, and transform template populations in .vertex files.
Populations are the parameter rows that instantiate a .loop template N times.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .ast import FromFile, SourceParams, TemplateSource, VertexFile


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PopulationRow:
    """One row in a template population."""

    key: str  # first column value
    values: dict[str, str]  # all columns including key


@dataclass(frozen=True)
class PopulationInfo:
    """Complete population for a template source."""

    template_name: str
    header: list[str]
    rows: list[PopulationRow]
    storage: str  # "file" | "inline" | "both"
    file_path: Path | None
    vertex_path: Path


# ---------------------------------------------------------------------------
# Vertex + template resolution
# ---------------------------------------------------------------------------


def resolve_vertex(name_or_path: str, home: Path) -> Path:
    """Name or path -> .vertex file path.

    - Has .vertex extension -> use as-is
    - Starts with . or / -> use as-is (filesystem path)
    - Otherwise -> home / name / name.vertex
    """
    if (
        name_or_path.endswith(".vertex")
        or name_or_path.startswith("./")
        or name_or_path.startswith("/")
    ):
        return Path(name_or_path)
    return home / name_or_path / f"{name_or_path}.vertex"


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
# KDL text manipulation
# ---------------------------------------------------------------------------


def _find_template_block(
    lines: list[str], template_path_str: str
) -> tuple[int, int]:
    """Find template block by path string. Returns (first_line_idx, last_line_idx).

    Scans for 'template "path" {' and tracks brace nesting.
    Compares paths via Path() to handle ./ normalization.
    """
    target = Path(template_path_str)
    start = -1
    depth = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if start == -1:
            if stripped.startswith("template") and "{" in stripped:
                match = re.search(r'"([^"]+)"', stripped)
                if match and Path(match.group(1)) == target:
                    start = i
                    depth = stripped.count("{") - stripped.count("}")
                    if depth == 0:
                        return start, i
        else:
            depth += stripped.count("{") - stripped.count("}")
            if depth <= 0:
                return start, i

    if start != -1:
        raise ValueError(f"Unclosed template block for {template_path_str}")
    raise ValueError(f"Template block not found for {template_path_str}")


def _detect_indent(lines: list[str], start: int, end: int) -> str:
    """Detect indentation of children within a block."""
    for i in range(start + 1, end + 1):
        stripped = lines[i].strip()
        if stripped and stripped != "}":
            return lines[i][: len(lines[i]) - len(lines[i].lstrip())]
    # Fallback: template line indent + 2 spaces
    template_indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
    return template_indent + "  "


def kdl_insert_with_row(
    text: str, template_path_str: str, values: dict[str, str]
) -> str:
    """Insert a 'with' line into a template block.

    Inserts after the last existing 'with' or 'from' line,
    or after the template opening line.
    """
    had_trailing = text.endswith("\n")
    lines = text.splitlines()
    start, end = _find_template_block(lines, template_path_str)

    # Build the with line
    props = " ".join(f'{k}="{v}"' for k, v in values.items())

    # Find insertion point and indentation
    insert_at = start + 1
    indent = _detect_indent(lines, start, end)

    for i in range(start + 1, end + 1):
        stripped = lines[i].strip()
        if stripped.startswith("with ") or stripped.startswith("from "):
            insert_at = i + 1
            indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]

    lines.insert(insert_at, f"{indent}with {props}")
    result = "\n".join(lines)
    if had_trailing:
        result += "\n"
    return result


def kdl_remove_with_row(
    text: str, template_path_str: str, key_field: str, key_value: str
) -> str:
    """Remove the 'with' row where key_field matches key_value."""
    had_trailing = text.endswith("\n")
    lines = text.splitlines()
    start, end = _find_template_block(lines, template_path_str)

    needle = f'{key_field}="{key_value}"'
    for i in range(start + 1, end + 1):
        stripped = lines[i].strip()
        if stripped.startswith("with ") and needle in stripped:
            lines.pop(i)
            result = "\n".join(lines)
            if had_trailing:
                result += "\n"
            return result

    raise ValueError(f"No with row matching {key_field}={key_value!r}")


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

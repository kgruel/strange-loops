"""Markdown-based slide loader with zoom levels and auto-navigation.

Loads slides from markdown files with YAML frontmatter. Supports zoom-level
markers for progressive detail, and computes navigation from group+order.

Example:
    ---
    id: cell
    title: Cell
    group: primitives
    order: 1
    ---

    # Cell

    the atomic unit: one **character** + one `style`

    [zoom:0]

    ```python
    cell = Cell("A", Style(fg="red", bold=True))
    ```

    ↓ for detail

    [zoom:1]

    ```python
    @dataclass(frozen=True)
    class Cell:
        char: str
        style: Style
    ```

    [zoom:2]

    ```python
    # full source from docgen
    ```
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from painted import Style, Span, Line


# -- Group ordering for auto-navigation --

GROUP_ORDER = ["primitives", "composition", "application", "components"]


# -- Parsed Types (intermediate representation) --

@dataclass
class ParsedSlide:
    """Intermediate representation of a parsed markdown slide."""
    id: str
    title: str = ""
    group: str = ""
    order: int = 0
    align: str = "left"  # "left" or "center" — slide-level default for text sections
    common_sections: list[dict] = field(default_factory=list)
    zoom_sections: dict[int, list[dict]] = field(default_factory=dict)
    max_zoom: int = 0


# -- Style Mapping --

KEYWORD_STYLE = Style(fg="cyan", bold=True)
EMPHASIS_STYLE = Style(bold=True)
DIM_STYLE = Style(dim=True)
CODE_STYLE = Style(fg="yellow")


# -- Frontmatter Parser --

def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML frontmatter and body from markdown.

    Returns (frontmatter_dict, body_text).
    """
    if not content.startswith('---'):
        return {}, content

    # Find closing ---
    end_match = re.search(r'\n---\s*\n', content[3:])
    if not end_match:
        return {}, content

    yaml_text = content[3:end_match.start() + 3]
    body = content[end_match.end() + 3:]

    # Simple YAML parser (handles our subset)
    frontmatter = parse_simple_yaml(yaml_text)
    return frontmatter, body


def parse_simple_yaml(text: str) -> dict:
    """Parse simple YAML (flat keys only).

    Handles:
        key: value
        order: 1
    """
    result = {}

    for line in text.split('\n'):
        if not line.strip() or line.strip().startswith('#'):
            continue

        stripped = line.strip()

        if ':' not in stripped:
            continue

        key, _, value = stripped.partition(':')
        key = key.strip()
        value = value.strip()

        if value:
            # Try to parse as int
            try:
                result[key] = int(value)
            except ValueError:
                result[key] = value

    return result


# -- Markdown Body Parser --

def _parse_sections(lines: list[str], start: int, default_align: str = "left") -> tuple[list[dict], int]:
    """Parse lines into sections until EOF or a [zoom:N] marker.

    Returns (sections, next_line_index).

    [align:center] or [align:left] overrides alignment for the next text section only,
    then reverts to default_align.
    """
    sections: list[dict] = []
    i = start
    next_align: str | None = None  # one-shot override

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Stop at zoom marker
        if re.match(r'\[zoom:\d+\]', stripped):
            break

        # Skip docgen comment markers (pass through)
        if stripped.startswith('<!-- docgen:'):
            i += 1
            continue

        # Align marker [align:center] or [align:left]
        align_match = re.match(r'\[align:(left|center)\]', stripped)
        if align_match:
            next_align = align_match.group(1)
            i += 1
            continue

        # Code block
        if stripped.startswith('```'):
            lang = stripped[3:].strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing ```

            sections.append({
                'type': 'code',
                'source': '\n'.join(code_lines),
                'lang': lang or 'python',
            })
            continue

        # Demo marker [demo:id]
        demo_match = re.match(r'\[demo:(\w+)\]', stripped)
        if demo_match:
            sections.append({
                'type': 'demo',
                'demo_id': demo_match.group(1),
            })
            i += 1
            continue

        # Spacer marker [spacer] or [spacer:N]
        spacer_match = re.match(r'\[spacer(?::(\d+))?\]', stripped)
        if spacer_match:
            n = int(spacer_match.group(1)) if spacer_match.group(1) else 1
            sections.append({
                'type': 'spacer',
                'lines': n,
            })
            i += 1
            continue

        # Empty line → skip
        if not stripped:
            i += 1
            continue

        # Regular text paragraph
        para_lines = []
        while i < len(lines):
            l = lines[i].strip()
            if not l or l.startswith('```') or l.startswith('#') or l.startswith('[') or l.startswith('<!--'):
                break
            para_lines.append(l)
            i += 1

        if para_lines:
            text = ' '.join(para_lines)
            # Determine centering: one-shot override > slide default
            align = next_align or default_align
            next_align = None  # consume the override
            sections.append({
                'type': 'text',
                'content': text,
                'center': align == "center",
            })

    return sections, i


def parse_body(body: str, default_align: str = "left") -> tuple[str, list[dict], dict[int, list[dict]], int]:
    """Parse markdown body into title, common sections, and zoom sections.

    Returns (title, common_sections, zoom_sections, max_zoom).

    Content before first [zoom:N] marker is common (shown at all zoom levels).
    Content after [zoom:N] is shown only at that level (replacement, not additive).
    default_align is passed through to text sections as the centering default.
    """
    lines = body.split('\n')
    title = ""

    # Find title (first h1)
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith('# '):
            title = stripped[2:].strip()
            i += 1
            break
        # Non-empty, non-heading — stop looking for title
        break

    # Parse common sections (before any [zoom:N])
    common_sections, i = _parse_sections(lines, i, default_align)

    # Parse zoom sections
    zoom_sections: dict[int, list[dict]] = {}
    max_zoom = 0

    while i < len(lines):
        stripped = lines[i].strip()
        zoom_match = re.match(r'\[zoom:(\d+)\]', stripped)
        if zoom_match:
            level = int(zoom_match.group(1))
            max_zoom = max(max_zoom, level)
            i += 1
            sections, i = _parse_sections(lines, i, default_align)
            zoom_sections[level] = sections
        else:
            i += 1

    return title, common_sections, zoom_sections, max_zoom


def parse_styled_text(text: str) -> Line:
    """Parse markdown-style text into a styled Line.

    Supports:
        **bold** → bold
        *dim* → dim
        `code` → keyword style
        {color:text} → explicit color
    """
    spans = []
    pos = 0

    # Pattern matches: **bold**, *dim*, `code`, {color:text}
    pattern = re.compile(
        r'\*\*(.+?)\*\*'        # **bold**
        r'|\*(.+?)\*'           # *dim*
        r'|`(.+?)`'             # `code`
        r'|\{(\w+):([^}]+)\}'   # {color:text}
    )

    for match in pattern.finditer(text):
        # Add plain text before this match
        if match.start() > pos:
            spans.append(Span(text[pos:match.start()]))

        if match.group(1):  # **bold**
            spans.append(Span(match.group(1), EMPHASIS_STYLE))
        elif match.group(2):  # *dim*
            spans.append(Span(match.group(2), DIM_STYLE))
        elif match.group(3):  # `code`
            spans.append(Span(match.group(3), KEYWORD_STYLE))
        elif match.group(4) and match.group(5):  # {color:text}
            color = match.group(4)
            content = match.group(5)
            spans.append(Span(content, Style(fg=color)))

        pos = match.end()

    # Add remaining plain text
    if pos < len(text):
        spans.append(Span(text[pos:]))

    if not spans:
        spans.append(Span(text))

    return Line(spans=tuple(spans))


# -- Validation --

class SlideValidationError(Exception):
    """Raised when slide validation fails."""


def validate_slides(slides: dict[str, ParsedSlide]) -> None:
    """Validate a collection of parsed slides.

    Checks:
    - Unique IDs (enforced by dict, but check for file-level collisions)
    - Known groups (must be in GROUP_ORDER or empty for standalone)
    - Contiguous zoom levels (no gaps: 0, 1, 2 not 0, 2)
    - No duplicate (group, order) pairs within a group
    """
    # Check known groups
    valid_groups = set(GROUP_ORDER) | {""}
    for slide in slides.values():
        if slide.group and slide.group not in valid_groups:
            raise SlideValidationError(
                f"Slide '{slide.id}': unknown group '{slide.group}'. "
                f"Valid groups: {GROUP_ORDER}"
            )

    # Check contiguous zoom levels
    for slide in slides.values():
        if slide.max_zoom > 0:
            for level in range(slide.max_zoom + 1):
                if level not in slide.zoom_sections:
                    raise SlideValidationError(
                        f"Slide '{slide.id}': missing zoom level {level}. "
                        f"max_zoom={slide.max_zoom} but levels {sorted(slide.zoom_sections.keys())} present."
                    )

    # Check unique (group, order) within groups
    seen: dict[str, dict[int, str]] = {}
    for slide in slides.values():
        if not slide.group:
            continue
        if slide.group not in seen:
            seen[slide.group] = {}
        if slide.order in seen[slide.group]:
            raise SlideValidationError(
                f"Slide '{slide.id}': duplicate order {slide.order} in group '{slide.group}'. "
                f"Already used by '{seen[slide.group][slide.order]}'."
            )
        seen[slide.group][slide.order] = slide.id


# -- Auto-Navigation --

def build_navigation(slides: dict[str, ParsedSlide]) -> dict[str, dict[str, str | None]]:
    """Compute left/right navigation from group+order sorting.

    Returns dict mapping slide_id -> {left, right, up, down}.

    Sequence: intro first, then groups by GROUP_ORDER + order, then fin last.
    Up/down are not assigned — zoom is handled by tour.py.
    """
    # Sort slides into sequence
    standalone_intro = []
    grouped: dict[str, list[ParsedSlide]] = {g: [] for g in GROUP_ORDER}
    standalone_fin = []
    other_standalone = []

    for slide in slides.values():
        if slide.id == "intro":
            standalone_intro.append(slide)
        elif slide.id == "fin":
            standalone_fin.append(slide)
        elif slide.group in grouped:
            grouped[slide.group].append(slide)
        else:
            other_standalone.append(slide)

    # Sort within groups by order
    for group in grouped:
        grouped[group].sort(key=lambda s: s.order)

    # Build sequence
    sequence: list[str] = []
    for slide in standalone_intro:
        sequence.append(slide.id)
    for group in GROUP_ORDER:
        for slide in grouped[group]:
            sequence.append(slide.id)
    for slide in other_standalone:
        sequence.append(slide.id)
    for slide in standalone_fin:
        sequence.append(slide.id)

    # Assign left/right
    nav: dict[str, dict[str, str | None]] = {}
    for i, sid in enumerate(sequence):
        nav[sid] = {
            'left': sequence[i - 1] if i > 0 else None,
            'right': sequence[i + 1] if i < len(sequence) - 1 else None,
            'up': None,
            'down': None,
        }

    return nav


def get_navigation_sequence(slides: dict[str, ParsedSlide]) -> list[str]:
    """Return the ordered slide ID sequence (for minimap, quiet mode, etc.)."""
    nav = build_navigation(slides)
    # Reconstruct from left/right chain starting at first slide with no left
    sequence = []
    # Find the start (slide with no left)
    start = None
    for sid, n in nav.items():
        if n['left'] is None:
            start = sid
            break
    if start is None:
        return list(slides.keys())

    current = start
    visited: set[str] = set()
    while current and current not in visited:
        visited.add(current)
        sequence.append(current)
        current = nav[current]['right']

    return sequence


# -- Main Loader --

def load_slide_md(path: Path | str) -> ParsedSlide:
    """Load a single markdown file into a ParsedSlide."""
    path = Path(path)
    content = path.read_text()

    frontmatter, body = parse_frontmatter(content)
    align = frontmatter.get('align', 'left')
    title, common_sections, zoom_sections, max_zoom = parse_body(body, default_align=align)

    return ParsedSlide(
        id=frontmatter.get('id', path.stem),
        title=frontmatter.get('title', title) or title,
        group=frontmatter.get('group', ''),
        order=frontmatter.get('order', 0),
        align=align,
        common_sections=common_sections,
        zoom_sections=zoom_sections,
        max_zoom=max_zoom,
    )


def load_slides_dir(dir_path: Path | str) -> dict[str, ParsedSlide]:
    """Load all markdown slides from a directory (recursive)."""
    dir_path = Path(dir_path)
    slides = {}

    for md_file in sorted(dir_path.rglob('*.md')):
        slide = load_slide_md(md_file)
        if slide.id in slides:
            raise SlideValidationError(
                f"Duplicate slide ID '{slide.id}' in {md_file} "
                f"(already loaded from another file)."
            )
        slides[slide.id] = slide

    return slides


# -- CLI for testing --

if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python slide_loader.py <file_or_dir>")
        sys.exit(1)

    path = Path(sys.argv[1])

    if path.is_dir():
        parsed = load_slides_dir(path)
        validate_slides(parsed)
        nav = build_navigation(parsed)
        seq = get_navigation_sequence(parsed)

        print(f"Loaded {len(parsed)} slides")
        print(f"Sequence: {' -> '.join(seq)}")
        print()
        for sid in seq:
            slide = parsed[sid]
            n = nav.get(sid, {})
            print(f"  {sid} (group={slide.group}, order={slide.order}, max_zoom={slide.max_zoom})")
            print(f"    common: {len(slide.common_sections)} sections")
            for level in sorted(slide.zoom_sections):
                print(f"    zoom {level}: {len(slide.zoom_sections[level])} sections")
            print(f"    nav: left={n.get('left')}, right={n.get('right')}")
    else:
        parsed = load_slide_md(path)
        print(f"ID: {parsed.id}")
        print(f"Title: {parsed.title}")
        print(f"Group: {parsed.group}, Order: {parsed.order}")
        print(f"Max zoom: {parsed.max_zoom}")
        print(f"Common sections ({len(parsed.common_sections)}):")
        for i, sec in enumerate(parsed.common_sections):
            print(f"  {i+1}. {sec}")
        for level in sorted(parsed.zoom_sections):
            print(f"Zoom {level} sections ({len(parsed.zoom_sections[level])}):")
            for i, sec in enumerate(parsed.zoom_sections[level]):
                print(f"  {i+1}. {sec}")

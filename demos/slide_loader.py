"""Markdown-based slide loader.

Loads slides from markdown files with YAML frontmatter.

Example:
    ---
    id: cell
    nav:
      left: intro
      right: style
      down: cell/detail
    ---

    # Cell

    the atomic unit: one **character** + one `style`

    ```python
    cell = Cell("A", Style(fg="red", bold=True))
    ```

    [demo:spinner]

    ↓ for more detail
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from fidelis import Style, Span, Line


# -- Parsed Types (intermediate representation) --

@dataclass
class ParsedNav:
    left: str | None = None
    right: str | None = None
    up: str | None = None
    down: str | None = None


@dataclass
class ParsedSlide:
    """Intermediate representation of a parsed markdown slide."""
    id: str
    title: str = ""
    nav: ParsedNav = field(default_factory=ParsedNav)
    sections: list[dict] = field(default_factory=list)  # [{type: ..., ...}]


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
    """Parse simple YAML (flat keys, nested dicts one level deep).

    Handles:
        key: value
        nav:
          left: intro
          right: style
    """
    result = {}
    current_dict = None
    current_key = None

    for line in text.split('\n'):
        if not line.strip() or line.strip().startswith('#'):
            continue

        # Check indentation
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        if ':' not in stripped:
            continue

        key, _, value = stripped.partition(':')
        key = key.strip()
        value = value.strip()

        if indent == 0:
            if value:
                result[key] = value
                current_dict = None
            else:
                # Start of nested dict
                result[key] = {}
                current_dict = result[key]
                current_key = key
        elif indent > 0 and current_dict is not None:
            current_dict[key] = value

    return result


# -- Markdown Body Parser --

def parse_body(body: str) -> tuple[str, list[dict]]:
    """Parse markdown body into title and sections.

    Returns (title, sections_list).
    """
    lines = body.split('\n')
    title = ""
    sections = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines at start
        if not stripped and not sections:
            i += 1
            continue

        # Heading → title (first h1 only)
        if stripped.startswith('# ') and not title:
            title = stripped[2:].strip()
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

        # Empty line → skip (just paragraph separator, use [spacer] for explicit spacing)
        if not stripped:
            i += 1
            continue

        # Regular text paragraph
        para_lines = []
        while i < len(lines):
            l = lines[i].strip()
            if not l or l.startswith('```') or l.startswith('#') or l.startswith('['):
                break
            para_lines.append(l)
            i += 1

        if para_lines:
            text = ' '.join(para_lines)
            sections.append({
                'type': 'text',
                'content': text,
                'center': text.startswith('↓') or text.startswith('→'),  # hint detection
            })

    return title, sections


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


# -- Main Loader --

def load_slide_md(path: Path | str) -> ParsedSlide:
    """Load a single markdown file into a ParsedSlide."""
    path = Path(path)
    content = path.read_text()

    frontmatter, body = parse_frontmatter(content)
    title, sections = parse_body(body)

    # Extract nav
    nav_data = frontmatter.get('nav', {})
    if isinstance(nav_data, str):
        nav_data = {}

    nav = ParsedNav(
        left=nav_data.get('left'),
        right=nav_data.get('right'),
        up=nav_data.get('up'),
        down=nav_data.get('down'),
    )

    return ParsedSlide(
        id=frontmatter.get('id', path.stem),
        title=frontmatter.get('title', title),
        nav=nav,
        sections=sections,
    )


def load_slides_dir(dir_path: Path | str) -> dict[str, ParsedSlide]:
    """Load all markdown slides from a directory."""
    dir_path = Path(dir_path)
    slides = {}

    for md_file in sorted(dir_path.glob('*.md')):
        slide = load_slide_md(md_file)
        slides[slide.id] = slide

    return slides


# -- Conversion to Bench Types --

def to_bench_slide(parsed: ParsedSlide):
    """Convert ParsedSlide to bench.py Slide type.

    Import bench types here to avoid circular imports.
    """
    from demos.bench import Slide, Navigation, Text, Code, Demo, Spacer, SUBTITLE_STYLE, HINT_STYLE

    sections = []
    for sec in parsed.sections:
        if sec['type'] == 'spacer':
            sections.append(Spacer(sec.get('lines', 1)))
        elif sec['type'] == 'text':
            line = parse_styled_text(sec['content'])
            style = HINT_STYLE if sec.get('center') else SUBTITLE_STYLE
            sections.append(Text(line, style, center=sec.get('center', False)))
        elif sec['type'] == 'code':
            sections.append(Code(source=sec['source'], title=sec.get('lang', '')))
        elif sec['type'] == 'demo':
            sections.append(Demo(demo_id=sec['demo_id']))

    return Slide(
        id=parsed.id,
        title=parsed.title,
        sections=tuple(sections),
        nav=Navigation(
            left=parsed.nav.left,
            right=parsed.nav.right,
            up=parsed.nav.up,
            down=parsed.nav.down,
        ),
    )


# -- CLI for testing --

if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python slide_loader.py <file.md>")
        sys.exit(1)

    path = Path(sys.argv[1])
    parsed = load_slide_md(path)

    print(f"ID: {parsed.id}")
    print(f"Title: {parsed.title}")
    print(f"Nav: left={parsed.nav.left}, right={parsed.nav.right}, up={parsed.nav.up}, down={parsed.nav.down}")
    print(f"Sections ({len(parsed.sections)}):")
    for i, sec in enumerate(parsed.sections):
        print(f"  {i+1}. {sec}")

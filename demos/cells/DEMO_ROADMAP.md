# Demo Roadmap: Interactive Teaching Bench

An interactive, navigable educational platform that uses `cells` to teach `cells`.

## Concept

A 2D navigable space where:
- **←/→** moves between topics (sibling concepts at same depth)
- **↑/↓** moves between depths (same concept, more/less detail)
- Every screen uses the full framework to render its own explanation
- Code shown = code used (self-demonstrating)

## Navigation Structure

Not a linear slideshow — a graph of connected concepts:

```
                        [Cell deep]
                            ↑
[Intro] ← → [Cell] ← → [Style] ← → [Span] ← → [Line]
                            ↓
                        [Cell examples]

                [Buffer] ← → [BufferView]
                    ↓
                [Block] ← → [Compose]
                    ↓
                [Components]
```

Horizontal = peer concepts at same abstraction level.
Vertical = deeper/simpler on the same concept.

## Data Model

```python
SlideId = str  # e.g. "cell", "cell/deep", "style"

@dataclass(frozen=True)
class Slide:
    id: SlideId
    title: str
    sections: tuple[Section, ...]
    nav: Navigation
    on_key: Callable[[str, State], State] | None = None

@dataclass(frozen=True)
class Navigation:
    up: SlideId | None = None
    down: SlideId | None = None
    left: SlideId | None = None
    right: SlideId | None = None

Section = Text | Code | Demo | Spacer
```

## Phases

### Phase 1: Navigation Infrastructure ✓ complete
- [x] SlideApp base with 4-way navigation
- [x] Slide registry (dict of slides)
- [x] Header (title) + footer (nav hints)
- [x] Placeholder slides for structure testing (12 slides)
- [x] Position indicator (slide id in footer)

### Phase 2: Content Rendering ✓ complete
- [x] Text sections with Line/Span styling (`styled()` helper)
- [x] Code sections with Python syntax highlighting
- [x] Spacer for layout control
- [x] Proper width handling / centering (code blocks centered by default)

### Phase 3: Interactive Demos ✓ complete
- [x] Demo section type with embedded widgets
- [x] Per-slide state management (BenchState holds component states)
- [x] Slide-specific key handlers (context-aware: nav vs. widget interaction)
- [x] Working examples: spinner (3 types), progress bar, list view, text input

### Phase 4: Polish ✓ complete
- [x] Help overlay (`?` key, any key dismisses)
- [x] Focus indicator in footer (`FOCUS` badge when demo focused)
- [x] Navigation dims when focused (visual hierarchy)
- [x] Help hint in footer (`?:help`)
- [ ] ~~Slide transitions~~ (deferred: instant feels snappier for learning)
- [ ] ~~Entry animations~~ (deferred: adds complexity without clear value)

### Phase 5: Content Authoring
- [x] Core curriculum complete (17 slides)
- [x] Primitives covered: Cell, Style, Span, Line, Buffer, BufferView, Block, Compose
- [x] Application layer: RenderApp, Components
- [x] Interactive examples for all component types
- [ ] Self-documenting slides (show the code that renders this slide)
- [ ] Additional depth slides for advanced topics

## Open Questions

1. **Slide definitions** — Start with Python dataclasses, evaluate YAML/external later
2. **Code highlighting** — Minimal keyword coloring (def, class, return, etc.)
3. **State scoping** — Global AppState with slide-specific substates
4. **Position display** — Simple "topic / depth" text for now, visual map later

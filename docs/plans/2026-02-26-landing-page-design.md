# Landing Page Design

Single static HTML page for painted. The showcase — one beautiful page that tells the adoption ladder story with companion GIFs and code examples.

## Architecture

Plain HTML + CSS, no build step. GitHub Pages serves `site/` directly. Only external dependency: Prism.js CDN for Python syntax highlighting.

Zero build dependencies mirrors painted's own "one dependency" philosophy. The page itself demonstrates the aesthetic sensibility.

## Content Flow

Top-to-bottom scroll story. Each section pairs a tight code example with its companion GIF. Sections alternate sides (code-left/GIF-right, GIF-left/code-right) for visual rhythm. Mobile stacks vertically.

| # | Section | Content | GIF |
|---|---------|---------|-----|
| 1 | Hero | Name, tagline, 2-line `show()` example | `hero.gif` |
| 2 | Print styled output | `print_block` code | `styled.gif` |
| 3 | Compose | `border(join_vertical(...))` code | `compose.gif` |
| 4 | CLI harness | `run_cli` code + bash flags | `zoom.gif` |
| 5 | Full TUI | `Surface` subclass code | `tui.gif` |
| 6 | Install | `pip install painted` | — |
| 7 | Footer | GitHub, PyPI links | — |

### Section Detail

**Hero:** "painted" in monospace. Tagline: "One library. Print to TUI. One dependency." Hero GIF centered below. Two-line code example:

```python
from painted import show
show({"cpu": 67, "mem": 82, "disk": 45})
```

Below: "TTY gets a styled chart. Pipe gets plain text. `--json` gets JSON."

**Ladder sections (2-5):** Each has:
- Section heading
- One-sentence description
- Code block (from current README — already good)
- Companion GIF

Alternating layout creates visual rhythm without repetition.

**Install:** Centered, minimal. `pip install painted`. Note about wcwidth being the sole dependency.

**Footer:** GitHub repo link, PyPI link. No social, no newsletter, no analytics.

## Visual Design

### Color System

CSS custom properties for all colors. Semantic names, not color names. Currently Catppuccin Mocha (dark) and Latte (light). Designed to be swapped for custom design tokens before release.

```css
:root {
  /* Light mode (Catppuccin Latte — swap later) */
  --page-bg: #eff1f5;
  --text: #4c4f69;
  --text-muted: #9ca0b0;
  --code-bg: #e6e9ef;
  --code-border: #dce0e8;
  --accent: #1e66f5;
  --success: #40a02b;
}

@media (prefers-color-scheme: dark) {
  :root {
    /* Dark mode (Catppuccin Mocha — swap later) */
    --page-bg: #1e1e2e;
    --text: #cdd6f4;
    --text-muted: #6c7086;
    --code-bg: #181825;
    --code-border: #313244;
    --accent: #89b4fa;
    --success: #a6e3a1;
  }
}
```

### Typography

- Body: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`
- Code: `ui-monospace, "SF Mono", Menlo, Monaco, "Cascadia Code", monospace`
- Hero "painted": monospace, large
- Section headings: body font, bold

### GIF Presentation

- 8px border-radius (matches VHS recording's `BorderRadius 8`)
- Light mode: subtle `box-shadow` to give depth against light background
- Dark mode: no shadow, GIFs blend with page (Catppuccin Mocha matches)
- Responsive: scale with viewport, `max-width: 100%`

### Layout

- Max-width: 960px, centered
- Generous vertical rhythm (80-120px between sections)
- Desktop: two-column flex (code + GIF, alternating sides)
- Mobile (<768px): single column, stack vertically
- Breakpoint: one, at 768px

### Syntax Highlighting

Prism.js from CDN:
- Core: `prism-core.min.js` (~2KB)
- Language: `prism-python.min.js`
- Theme: Catppuccin-compatible (custom CSS targeting Prism tokens to use `--code-*` variables)

## File Structure

```
site/
  index.html       # the page
  style.css        # design tokens + layout + responsive
  img/             # companion GIFs (copied from tapes/)
    hero.gif
    styled.gif
    compose.gif
    zoom.gif
    tui.gif
```

GIFs are copied (not symlinked) to `site/img/` so the site directory is self-contained for GitHub Pages.

## GitHub Pages Setup

- Source: `site/` directory on `main` branch (or `gh-pages` branch)
- No build step, no GitHub Actions needed
- Custom domain: configurable later via CNAME file

## Design Principles

1. **One swap point** — All visual identity in CSS custom properties. Swap Catppuccin for your own tokens by changing one block.
2. **No build step** — Matches painted's minimalism. HTML + CSS + CDN.
3. **Content-first** — GIFs and code do the talking. Minimal prose.
4. **The page IS the proof** — A terminal UI framework's landing page demonstrates its taste.

## Relationship to Companion GIFs

The companion GIFs plan (`2026-02-26-companion-gifs-plan.md`) produces the GIF assets this page consumes. The GIFs are designed for README inline use AND landing page use — same assets, different contexts.

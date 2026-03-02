# Landing Page Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Use superpowers:frontend-design for Task 2 (the HTML/CSS implementation).

**Goal:** Single static HTML landing page showcasing painted's adoption ladder with companion GIFs and code examples.

**Architecture:** Plain HTML + CSS, no build step. CSS custom properties for dark/light adaptive theming. Prism.js CDN for syntax highlighting. GitHub Pages serves `site/` directly.

**Tech Stack:** HTML5, CSS3 (custom properties, flexbox, media queries), Prism.js (CDN)

**Design doc:** `docs/plans/2026-02-26-landing-page-design.md`

**Prerequisite:** Companion GIFs must be recorded first (`docs/plans/2026-02-26-companion-gifs-plan.md`). If GIFs don't exist yet, use placeholder `<img>` tags with `alt` text and swap in real GIFs later.

---

### Task 1: Create site directory and placeholder GIFs

**Files:**
- Create: `site/` directory
- Create: `site/img/` directory

**Step 1: Create directory structure**

```bash
mkdir -p site/img
```

**Step 2: Copy existing GIFs if available, otherwise note placeholders**

```bash
# If companion GIFs exist:
for f in hero styled compose zoom tui; do
  [ -f "tapes/${f}.gif" ] && cp "tapes/${f}.gif" "site/img/${f}.gif"
done
ls -la site/img/
```

If no GIFs exist yet, that's fine — Task 2 uses `alt` text fallbacks. GIFs get swapped in when the companion GIF plan executes.

**Step 3: Commit**

```bash
git add site/
git commit -m "chore: create site directory for landing page"
```

---

### Task 2: Build the landing page HTML and CSS

This is the core task. Use the **frontend-design** skill for this step.

**Files:**
- Create: `site/index.html`
- Create: `site/style.css`

**Context the frontend-design agent needs:**

The page is a single-scroll showcase for a Python terminal UI library called "painted." It tells the adoption ladder story: show() → print_block → compose → CLI harness → full TUI. Each section pairs a code example with a companion GIF.

**Required sections (top to bottom):**

1. **Hero** — "painted" in monospace (large), tagline "One library. Print to TUI. One dependency.", hero GIF centered, 2-line show() code example, subtext "TTY gets a styled chart. Pipe gets plain text. `--json` gets JSON."

2. **Print styled output** — heading, one-line description "Replace print() one call at a time. Auto-detects TTY.", code block left + `styled.gif` right:
```python
from painted import Block, Style, print_block

block = Block.text("deploy OK", Style(fg="green", bold=True))
print_block(block)
```

3. **Compose** — heading, one-line description "Blocks are immutable rectangles. Compose them with functions.", `compose.gif` left + code block right:
```python
from painted import border, join_vertical, ROUNDED

header = Block.text(" api-gateway ", Style(bold=True, reverse=True))
status = join_vertical(
    Block.text("  replicas: 2/3 ready", Style(fg="yellow")),
    Block.text("  /health:  200  12ms", Style(fg="green")),
)
card = border(join_vertical(header, status), chars=ROUNDED)
print_block(card)
```

4. **CLI harness** — heading, one-line description "One render function, three output modes.", code block left + `zoom.gif` right:
```python
from painted import run_cli, CliContext, Block

def render(ctx: CliContext, data: dict) -> Block:
    ...  # your render logic

def fetch() -> dict:
    return {"status": "ok", "replicas": 3}

run_cli(sys.argv[1:], render=render, fetch=fetch)
```
Plus bash examples below:
```bash
myapp           # auto-detect
myapp -q        # quiet
myapp -v        # verbose
myapp -i        # interactive TUI
myapp --json    # JSON output
myapp | grep ok # plain text, no ANSI
```

5. **Full TUI** — heading, one-line description "Alt screen, keyboard input, diff-flush render loop.", `tui.gif` left + code block right:
```python
import asyncio
from painted import Block, Style, border
from painted.tui import Surface

class MyApp(Surface):
    def render(self):
        block = Block.text("Hello!", Style(fg="green"))
        border(block, title="Demo").paint(self._buf)

    def on_key(self, key: str):
        if key == "q":
            self.quit()

asyncio.run(MyApp().run())
```

6. **Install** — centered, `pip install painted`, note "One dependency: wcwidth"

7. **Footer** — GitHub link, PyPI link. Minimal.

**CSS requirements:**

- All colors as CSS custom properties in `:root` and `@media (prefers-color-scheme: dark)`
- Light mode defaults (Catppuccin Latte tokens):
  - `--page-bg: #eff1f5`, `--text: #4c4f69`, `--text-muted: #9ca0b0`
  - `--code-bg: #e6e9ef`, `--code-border: #dce0e8`
  - `--accent: #1e66f5`, `--success: #40a02b`
- Dark mode (Catppuccin Mocha tokens):
  - `--page-bg: #1e1e2e`, `--text: #cdd6f4`, `--text-muted: #6c7086`
  - `--code-bg: #181825`, `--code-border: #313244`
  - `--accent: #89b4fa`, `--success: #a6e3a1`
- Typography: system font stack for body, monospace stack for code
- Layout: max-width 960px, centered, flexbox for code+GIF pairs
- Responsive: single breakpoint at 768px, stack vertically on mobile
- GIFs: 8px border-radius, subtle box-shadow in light mode, max-width 100%
- Generous vertical spacing between sections (80-120px)
- Alternating layout: sections 2,4 are code-left/GIF-right; sections 3,5 are GIF-left/code-right

**Syntax highlighting:**
- Prism.js from CDN in `<head>`:
  - `https://cdn.jsdelivr.net/npm/prismjs@1/prism.min.js`
  - `https://cdn.jsdelivr.net/npm/prismjs@1/components/prism-python.min.js`
  - `https://cdn.jsdelivr.net/npm/prismjs@1/components/prism-bash.min.js`
- Do NOT include a Prism theme CSS — custom-style Prism tokens using the page's CSS variables so highlighting adapts to dark/light mode
- Code blocks use `<pre><code class="language-python">` / `<code class="language-bash">`

**GIF references:**
- `<img src="img/hero.gif" alt="show() producing styled output in TTY, plain text in pipe, JSON with --json flag">`
- Similar descriptive alt text for each GIF
- If GIF files don't exist in `site/img/`, the alt text serves as placeholder

**Step 1: Create `site/style.css`**

Write the complete CSS file with:
- CSS custom properties (light default + dark media query)
- Base reset and typography
- Layout classes for sections, code+GIF pairs, hero
- Responsive breakpoint
- Prism token overrides using CSS variables
- GIF styling

**Step 2: Create `site/index.html`**

Write the complete HTML file with:
- `<!DOCTYPE html>`, proper `<head>` with meta tags, CSS link, Prism CDN
- All 7 sections with exact code examples above
- Proper `<pre><code class="language-*">` blocks for Prism
- GIF `<img>` tags with descriptive alt text
- Semantic HTML: `<header>`, `<main>`, `<section>`, `<footer>`

**Step 3: Verify locally**

```bash
# Open in browser
open site/index.html
```

Verify:
- Page renders with proper layout
- Dark/light mode switches correctly (toggle in browser dev tools)
- Code blocks have syntax highlighting
- GIFs display (if present) or alt text shows (if not)
- Mobile layout works (resize browser to <768px)

**Step 4: Commit**

```bash
git add site/index.html site/style.css
git commit -m "feat: landing page with adaptive dark/light theme"
```

---

### Task 3: GitHub Pages configuration

**Files:**
- Create: `site/.nojekyll` (tells GitHub Pages not to process with Jekyll)

**Step 1: Create .nojekyll**

```bash
touch site/.nojekyll
```

This prevents GitHub from trying to process the site with Jekyll (which would ignore files starting with `_` or `.`).

**Step 2: Commit**

```bash
git add site/.nojekyll
git commit -m "chore: add .nojekyll for GitHub Pages"
```

**Step 3: Note for user**

GitHub Pages setup (manual, not automated):
1. Go to repo Settings → Pages
2. Source: "Deploy from a branch"
3. Branch: `main`, folder: `/site`
4. Save

Or use `gh` CLI:
```bash
gh api repos/{owner}/{repo}/pages -X POST -f source.branch=main -f source.path=/site
```

---

### Task 4: Update HANDOFF.md and LOG.md

**Files:**
- Modify: `HANDOFF.md`
- Modify: `LOG.md`

**Step 1: Add landing page to HANDOFF.md completed section**

Add entry to the "Completed" list:
```
- **Landing page** — Single static HTML page (`site/index.html`) for GitHub
  Pages. Adaptive dark/light theme via CSS custom properties (Catppuccin
  tokens, swappable). Alternating code+GIF layout telling the adoption
  ladder story. Prism.js CDN for syntax highlighting. Zero build step.
```

**Step 2: Add LOG entry**

Add session entry to LOG.md with what was built.

**Step 3: Commit**

```bash
git add HANDOFF.md LOG.md
git commit -m "docs: add landing page to handoff and log"
```

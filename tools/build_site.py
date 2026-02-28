from __future__ import annotations

import argparse
import html
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Page:
    key: str
    title: str
    source_md: Path
    output_html: Path


_FENCE_RE = re.compile(r"^```(?P<lang>[\w+-]+)?\s*$")
_HR_RE = re.compile(r"^\s{0,3}(-{3,}|\*{3,})\s*$")
_H_RE = re.compile(r"^(?P<h>#{1,6})\s+(?P<text>.+?)\s*$")
_UL_RE = re.compile(r"^\s*[-*]\s+(?P<text>.+?)\s*$")
_OL_RE = re.compile(r"^\s*(?P<n>\d+)\.\s+(?P<text>.+?)\s*$")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8", newline="\n")


def _inline_md(text: str) -> str:
    parts = re.split(r"(`[^`]+`)", text)
    out: list[str] = []
    for part in parts:
        if part.startswith("`") and part.endswith("`"):
            out.append(f"<code>{html.escape(part[1:-1])}</code>")
            continue
        s = html.escape(part)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\*(.+?)\*", r"<em>\1</em>", s)
        out.append(s)
    return "".join(out)


def markdown_to_html(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []

    para: list[str] = []
    in_ul = False
    in_ol = False
    in_code = False
    code_lang = "none"
    code_lines: list[str] = []

    def flush_para() -> None:
        nonlocal para
        if not para:
            return
        out.append(f"<p>{_inline_md(' '.join(para).strip())}</p>")
        para = []

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    for raw in lines:
        line = raw.rstrip("\n")

        if line.strip().startswith("<!--") and line.strip().endswith("-->"):
            continue

        if in_code:
            if line.strip() == "```":
                code = "\n".join(code_lines).rstrip("\n")
                lang = code_lang or "none"
                out.append(
                    f'<pre class="language-{lang}"><code class="language-{lang}">{html.escape(code)}</code></pre>'
                )
                in_code = False
                code_lang = "none"
                code_lines = []
            else:
                code_lines.append(raw)
            continue

        m_fence = _FENCE_RE.match(line)
        if m_fence:
            flush_para()
            close_lists()
            in_code = True
            code_lang = (m_fence.group("lang") or "none").strip()
            code_lines = []
            continue

        if not line.strip():
            flush_para()
            close_lists()
            continue

        if _HR_RE.match(line):
            flush_para()
            close_lists()
            out.append("<hr>")
            continue

        m_h = _H_RE.match(line)
        if m_h:
            flush_para()
            close_lists()
            level = len(m_h.group("h"))
            text = m_h.group("text")
            out.append(f"<h{level}>{_inline_md(text)}</h{level}>")
            continue

        if line.lstrip().startswith(">"):
            flush_para()
            close_lists()
            q_lines: list[str] = []
            q = line
            while q.lstrip().startswith(">"):
                q_lines.append(q.lstrip()[1:].lstrip())
                # handled by outer loop; break to avoid consuming next line
                break
            out.append(f"<blockquote><p>{_inline_md(' '.join(q_lines))}</p></blockquote>")
            continue

        m_ul = _UL_RE.match(line)
        if m_ul:
            flush_para()
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline_md(m_ul.group('text'))}</li>")
            continue

        m_ol = _OL_RE.match(line)
        if m_ol:
            flush_para()
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{_inline_md(m_ol.group('text'))}</li>")
            continue

        if line.lstrip().startswith("<") and line.rstrip().endswith(">"):
            flush_para()
            close_lists()
            out.append(line)
            continue

        para.append(line.strip())

    flush_para()
    close_lists()
    if in_code:
        code = "\n".join(code_lines).rstrip("\n")
        lang = code_lang or "none"
        out.append(
            f'<pre class="language-{lang}"><code class="language-{lang}">{html.escape(code)}</code></pre>'
        )

    return "\n".join(out) + "\n"


def render_page(*, template: str, page: Page, asset_prefix: str, active_key: str) -> str:
    content = markdown_to_html(_read_text(page.source_md)).rstrip("\n")
    nav = {
        "nav_quickstart": 'aria-current="page"' if active_key == "quickstart" else "",
        "nav_primitives": 'aria-current="page"' if active_key == "primitives" else "",
        "nav_composition": 'aria-current="page"' if active_key == "composition" else "",
        "nav_cli_harness": 'aria-current="page"' if active_key == "cli-harness" else "",
        "nav_tui": 'aria-current="page"' if active_key == "tui" else "",
    }

    html_doc = template
    html_doc = html_doc.replace("{{title}}", html.escape(page.title))
    html_doc = html_doc.replace("{{asset_prefix}}", asset_prefix)
    html_doc = html_doc.replace("{{content}}", content)
    for k, v in nav.items():
        html_doc = html_doc.replace(f"{{{{{k}}}}}", v)
    return html_doc


def build_site(*, repo_root: Path) -> list[Path]:
    site_root = repo_root / "site"
    template_path = repo_root / "tools" / "site_templates" / "layout.html"
    template = _read_text(template_path)

    pages = [
        Page(
            key="quickstart",
            title="painted — Quickstart",
            source_md=repo_root / "docs" / "pages" / "quickstart.md",
            output_html=site_root / "docs" / "quickstart.html",
        ),
        Page(
            key="primitives",
            title="painted — Primitives and Blocks",
            source_md=repo_root / "docs" / "guides" / "01-primitives-and-blocks.md",
            output_html=site_root / "docs" / "primitives.html",
        ),
        Page(
            key="composition",
            title="painted — Composition Layout",
            source_md=repo_root / "docs" / "guides" / "02-composition-layout.md",
            output_html=site_root / "docs" / "composition.html",
        ),
        Page(
            key="cli-harness",
            title="painted — CLI Harness Fidelity",
            source_md=repo_root / "docs" / "guides" / "04-cli-harness-fidelity.md",
            output_html=site_root / "docs" / "cli-harness.html",
        ),
        Page(
            key="tui",
            title="painted — TUI Core Layers",
            source_md=repo_root / "docs" / "guides" / "05-tui-core-surface-layers.md",
            output_html=site_root / "docs" / "tui.html",
        ),
    ]

    written: list[Path] = []
    for page in pages:
        if not page.source_md.exists():
            raise FileNotFoundError(f"Missing source: {page.source_md}")

        asset_prefix = "../" if page.output_html.parent == site_root / "docs" else ""
        html_doc = render_page(
            template=template,
            page=page,
            asset_prefix=asset_prefix,
            active_key=page.key,
        )
        _write_text(page.output_html, html_doc)
        written.append(page.output_html)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build static docs site into site/.")
    parser.add_argument("--repo-root", type=Path, default=_repo_root())
    args = parser.parse_args(argv)

    written = build_site(repo_root=args.repo_root)
    rel = [p.relative_to(args.repo_root) for p in written]
    print("Wrote:")
    for p in rel:
        print(f"  - {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


from __future__ import annotations

from pathlib import Path

import pytest

from painted import Block, Style, Zoom, render_html
from painted.cell import Cell


def _row_text(block: Block, y: int = 0) -> str:
    return "".join(c.char for c in block.row(y))


def test_render_html_empty_block() -> None:
    out = render_html(Block.empty(0, 0, Style()))
    assert out == '<pre class="painted-output"></pre>\n'


def test_render_html_escapes_special_chars() -> None:
    block = Block.text('<>&"', Style())
    out = render_html(block)
    assert "&lt;" in out
    assert "&gt;" in out
    assert "&amp;" in out
    assert "&quot;" in out
    assert "<span" not in out


def test_render_html_coalesces_adjacent_cells_with_same_style() -> None:
    style = Style(fg="red")
    block = Block([[Cell("a", style), Cell("b", style)]], width=2)
    out = render_html(block)
    assert out.count("<span") == 1
    assert "ab" in out


def test_render_html_dim_style_emits_opacity() -> None:
    out = render_html(Block.text("x", Style(dim=True)))
    assert "opacity: 0.6" in out


def test_render_html_reverse_swaps_fg_bg_when_set() -> None:
    block = Block([[Cell("x", Style(fg="red", bg="blue", reverse=True))]], width=1)
    out = render_html(block)
    assert "color: blue" in out
    assert "background-color: red" in out


def test_render_html_reverse_with_no_colors_uses_defaults() -> None:
    block = Block([[Cell("x", Style(reverse=True))]], width=1)
    out = render_html(block)
    assert "color: var(--painted-bg, var(--code-bg))" in out
    assert "background-color: var(--painted-fg, var(--text))" in out


def test_capture_demo_run_cli_shape(tmp_path: Path) -> None:
    demo = tmp_path / "demo_runcli.py"
    demo.write_text(
        "\n".join(
            [
                "from painted import Block, Style",
                "",
                "def _fetch():",
                "    return 'hi'",
                "",
                "def _render(ctx, data):",
                "    return Block.text(f'{data} width={ctx.width}', Style())",
                "",
            ]
        ),
        encoding="utf-8",
    )

    from tools.capture import capture_demo

    out = capture_demo(demo, Zoom.SUMMARY, width=17)
    assert isinstance(out, Block)
    assert "hi" in _row_text(out)
    assert "width=17" in _row_text(out)


def test_capture_demo_direct_output_shape(tmp_path: Path) -> None:
    demo = tmp_path / "demo_direct.py"
    demo.write_text(
        "\n".join(
            [
                "from painted import Block, Style, print_block",
                "",
                "def demo():",
                "    print_block(Block.text('yo', Style(fg='red')))",
                "",
            ]
        ),
        encoding="utf-8",
    )

    from tools.capture import capture_demo

    out = capture_demo(demo, "demo", width=80)
    assert isinstance(out, str)
    assert "yo" in out


def test_outputgen_update_html_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    demo = tmp_path / "demo_runcli.py"
    demo.write_text(
        "\n".join(
            [
                "from painted import Block, Style",
                "",
                "def _fetch():",
                "    return 'ok'",
                "",
                "def _render(ctx, data):",
                "    return Block.text(data, Style(fg='green'))",
                "",
            ]
        ),
        encoding="utf-8",
    )

    from tools import outputgen

    spec = outputgen.OutputSpec(
        name="demo",
        demo_path=demo.name,
        function_or_zoom=Zoom.SUMMARY,
        format="html",
        width=10,
    )
    monkeypatch.setattr(outputgen, "MANIFEST", {"demo": spec})

    html_doc = "\n".join(
        [
            "<html>",
            '<!-- outputgen:begin name="demo" -->',
            "stale",
            "<!-- outputgen:end -->",
            "</html>",
            "",
        ]
    )

    updated, touched = outputgen.update_html(html_doc, repo_root=tmp_path)
    assert touched == ["demo"]
    assert '<pre class="painted-output">' in updated
    assert "ok" in updated

    assert outputgen.check_html(updated, repo_root=tmp_path) == []
    updated2, touched2 = outputgen.update_html(updated, repo_root=tmp_path)
    assert touched2 == ["demo"]
    assert updated2 == updated


def test_outputgen_missing_manifest_entry_raises(tmp_path: Path) -> None:
    from tools import outputgen

    with pytest.raises(KeyError):
        outputgen.update_html(
            '<!-- outputgen:begin name="nope" -->\n<!-- outputgen:end -->\n',
            repo_root=tmp_path,
        )

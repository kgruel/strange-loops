from __future__ import annotations

import argparse
import ast
import dataclasses
import datetime as dt
import io
import json
import re
import sys
import tokenize
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Kind = Literal["definition", "signature", "docstring", "region"]


@dataclass(frozen=True, slots=True)
class Origin:
    path: str
    start_line: int
    end_line: int


@dataclass(frozen=True, slots=True)
class Snippet:
    id: str
    kind: Kind
    language: str
    title: str
    source: str
    origin: Origin


@dataclass(frozen=True, slots=True)
class NodeRef:
    module: str
    qualname: str


@dataclass(frozen=True, slots=True)
class NodeInfo:
    module: str
    qualname: str
    path: Path
    node: ast.AST
    start_line: int
    end_line: int


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _iso_utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def _module_for_path(py_file: Path, *, src_root: Path) -> str:
    rel = py_file.relative_to(src_root)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]  # strip .py
    if not parts:
        return "fidelis"
    return "fidelis." + ".".join(parts)


def _iter_fidelis_py_files(src_root: Path) -> Iterator[Path]:
    for path in sorted(src_root.rglob("*.py")):
        if path.name.startswith("."):
            continue
        yield path


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_lines(path: Path) -> list[str]:
    return _read_text(path).splitlines()


def _slice_lines(lines: list[str], start_line: int, end_line: int) -> str:
    # start/end are 1-based inclusive
    start_idx = max(0, start_line - 1)
    end_idx = max(0, end_line)
    return "\n".join(lines[start_idx:end_idx]).rstrip() + "\n"


def _decorator_start_line(node: ast.AST, default: int) -> int:
    decorators = getattr(node, "decorator_list", None)
    if not decorators:
        return default
    lines = [getattr(d, "lineno", default) for d in decorators if getattr(d, "lineno", None)]
    return min(lines, default=default)


def _iter_defs(module: ast.Module, *, module_name: str, path: Path) -> Iterator[NodeInfo]:
    def walk(body: list[ast.stmt], prefix: str) -> Iterator[NodeInfo]:
        for stmt in body:
            match stmt:
                case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                    name = stmt.name
                    qualname = f"{prefix}.{name}" if prefix else name
                    start = _decorator_start_line(stmt, getattr(stmt, "lineno", 1))
                    end = getattr(stmt, "end_lineno", None)
                    if end is None:
                        continue
                    yield NodeInfo(
                        module=module_name,
                        qualname=qualname,
                        path=path,
                        node=stmt,
                        start_line=start,
                        end_line=end,
                    )
                    if isinstance(stmt, ast.ClassDef):
                        yield from walk(stmt.body, qualname)
                case _:
                    continue

    yield from walk(module.body, "")


def index_fidelis_sources(*, repo_root: Path) -> dict[tuple[str, str], NodeInfo]:
    src_root = repo_root / "src" / "fidelis"
    if not src_root.exists():
        raise FileNotFoundError(f"Missing src root: {src_root}")

    index: dict[tuple[str, str], NodeInfo] = {}
    for py_file in _iter_fidelis_py_files(src_root):
        module_name = _module_for_path(py_file, src_root=src_root)
        parsed = ast.parse(_read_text(py_file), filename=str(py_file))
        for info in _iter_defs(parsed, module_name=module_name, path=py_file):
            index[(info.module, info.qualname)] = info
    return index


def _parse_selector(raw: str) -> tuple[str, Kind]:
    if "#" not in raw:
        raise ValueError(f"Selector missing #kind: {raw!r}")
    base, kind = raw.split("#", 1)
    kind_t: Kind
    if kind in ("definition", "signature", "docstring", "region"):
        kind_t = kind  # type: ignore[assignment]
    else:
        raise ValueError(f"Unknown kind {kind!r} in selector {raw!r}")
    return base, kind_t


def _parse_py_ref(base: str) -> NodeRef:
    # py:<module>:<qualname>
    if not base.startswith("py:"):
        raise ValueError(f"Not a py selector: {base!r}")
    rest = base[len("py:") :]
    module, sep, qualname = rest.partition(":")
    if not sep or not module or not qualname:
        raise ValueError(f"Bad py selector: {base!r}")
    return NodeRef(module=module, qualname=qualname)


def _parse_region_ref(base: str) -> tuple[str, str]:
    # region:<relative_path>:<region_id>
    if not base.startswith("region:"):
        raise ValueError(f"Not a region selector: {base!r}")
    rest = base[len("region:") :]
    path, sep, region_id = rest.partition(":")
    if not sep or not path or not region_id:
        raise ValueError(f"Bad region selector: {base!r}")
    return path, region_id


_REGION_BEGIN_RE = re.compile(r"^\s*#\s*doc:region\s+(?P<id>[\w.-]+)\s*$")
_REGION_END_RE = re.compile(r"^\s*#\s*doc:endregion\s+(?P<id>[\w.-]+)\s*$")


def extract_region(
    *,
    repo_root: Path,
    rel_path: str,
    region_id: str,
) -> tuple[str, Origin]:
    path = (repo_root / rel_path).resolve()
    if repo_root not in path.parents and path != repo_root:
        raise ValueError(f"Region path escapes repo root: {rel_path!r}")
    if not path.exists():
        raise FileNotFoundError(f"Region file not found: {rel_path}")

    lines = _read_lines(path)
    start_line = None
    end_line = None

    for i, line in enumerate(lines, start=1):
        m = _REGION_BEGIN_RE.match(line)
        if m and m.group("id") == region_id:
            start_line = i + 1
            break

    if start_line is None:
        raise KeyError(f"Region {region_id!r} not found in {rel_path}")

    for i in range(start_line, len(lines) + 1):
        m = _REGION_END_RE.match(lines[i - 1])
        if m and m.group("id") == region_id:
            end_line = i - 1
            break

    if end_line is None or end_line < start_line:
        raise ValueError(f"Region {region_id!r} missing end marker in {rel_path}")

    source = _slice_lines(lines, start_line, end_line)
    origin = Origin(path=rel_path, start_line=start_line, end_line=end_line)
    return source, origin


def _tokenize_from(path: Path) -> Iterator[tokenize.TokenInfo]:
    data = path.read_bytes()
    # tokenize uses 1-based rows for start positions
    return tokenize.tokenize(io.BytesIO(data).readline)


def extract_signature(node_info: NodeInfo) -> tuple[str, Origin]:
    lines = _read_lines(node_info.path)
    start_line = node_info.start_line

    tokens = _tokenize_from(node_info.path)
    depth = 0
    started = False
    end_pos: tuple[int, int] | None = None

    skip = {
        tokenize.ENCODING,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
    }

    for tok in tokens:
        if tok.type in skip:
            continue

        if tok.start[0] < start_line:
            continue

        if not started:
            # Wait until we hit 'def', 'class', or 'async' (for async def) after decorators.
            if tok.type == tokenize.NAME and tok.string in ("def", "class", "async"):
                started = True
            continue

        if tok.type == tokenize.OP and tok.string in "([{":
            depth += 1
        elif tok.type == tokenize.OP and tok.string in ")]}":
            depth = max(0, depth - 1)

        if tok.type == tokenize.OP and tok.string == ":" and depth == 0:
            end_pos = tok.end  # (row, col) of ':'
            break

    if end_pos is None:
        # Fall back to first line only
        end_line = start_line
        source = _slice_lines(lines, start_line, end_line)
        return source, Origin(
            path=str(node_info.path.relative_to(_repo_root())),
            start_line=start_line,
            end_line=end_line,
        )

    end_line = end_pos[0]
    source = _slice_lines(lines, start_line, end_line)
    return source, Origin(
        path=str(node_info.path.relative_to(_repo_root())),
        start_line=start_line,
        end_line=end_line,
    )


def extract_definition(node_info: NodeInfo) -> tuple[str, Origin]:
    lines = _read_lines(node_info.path)
    source = _slice_lines(lines, node_info.start_line, node_info.end_line)
    return source, Origin(
        path=str(node_info.path.relative_to(_repo_root())),
        start_line=node_info.start_line,
        end_line=node_info.end_line,
    )


def extract_docstring(node_info: NodeInfo) -> tuple[str, Origin]:
    # For docstrings, origin is still the node span; callers can choose to render as text.
    doc = ast.get_docstring(node_info.node, clean=True) or ""
    # Best-effort: docstring usually starts immediately after header.
    origin = Origin(
        path=str(node_info.path.relative_to(_repo_root())),
        start_line=node_info.start_line,
        end_line=node_info.end_line,
    )
    return doc.rstrip() + "\n", origin


def build_snippet_store(
    selectors: Iterable[str],
    *,
    repo_root: Path,
    index: dict[tuple[str, str], NodeInfo],
) -> dict[str, Snippet]:
    out: dict[str, Snippet] = {}

    for raw in selectors:
        base, kind = _parse_selector(raw)

        if base.startswith("py:"):
            ref = _parse_py_ref(base)
            key = (ref.module, ref.qualname)
            if key not in index:
                raise KeyError(f"Unknown symbol {ref.module}:{ref.qualname}")
            node_info = index[key]

            if kind == "definition":
                source, origin = extract_definition(node_info)
            elif kind == "signature":
                source, origin = extract_signature(node_info)
            elif kind == "docstring":
                source, origin = extract_docstring(node_info)
            else:
                raise ValueError(f"Unsupported kind for py selector: {kind}")

            snippet_id = f"{base}#{kind}"
            out[snippet_id] = Snippet(
                id=snippet_id,
                kind=kind,
                language="python" if kind != "docstring" else "text",
                title=ref.qualname,
                source=source,
                origin=origin,
            )
            continue

        if base.startswith("region:"):
            rel_path, region_id = _parse_region_ref(base)
            if kind != "region":
                raise ValueError("Region selectors must use #region")
            source, origin = extract_region(
                repo_root=repo_root,
                rel_path=rel_path,
                region_id=region_id,
            )
            snippet_id = f"{base}#{kind}"
            out[snippet_id] = Snippet(
                id=snippet_id,
                kind=kind,
                language="python",
                title=region_id,
                source=source,
                origin=origin,
            )
            continue

        raise ValueError(f"Unknown selector scheme: {raw!r}")

    return out


_BEGIN_RE = re.compile(r"<!--\s*docgen:begin\s+(?P<sel>[^ ]+)\s*-->")
_END_RE = re.compile(r"<!--\s*docgen:end\s*-->")


def find_docgen_selectors(markdown: str) -> list[str]:
    selectors: list[str] = []
    for m in _BEGIN_RE.finditer(markdown):
        selectors.append(m.group("sel").strip())
    return selectors


def _render_snippet_block(snippet: Snippet) -> str:
    if snippet.language == "text":
        # Docstrings are inserted as plain text blocks (no fences).
        return snippet.source.rstrip() + "\n"
    return f"```{snippet.language}\n{snippet.source.rstrip()}\n```\n"


def update_markdown(
    markdown: str,
    *,
    snippets: dict[str, Snippet],
) -> tuple[str, list[str]]:
    """Return (updated_markdown, updated_selectors)."""
    out: list[str] = []
    updated: list[str] = []

    lines = markdown.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _BEGIN_RE.search(line)
        if not m:
            out.append(line)
            i += 1
            continue

        selector = m.group("sel").strip()
        base, kind = _parse_selector(selector)
        snippet_id = f"{base}#{kind}"
        if snippet_id not in snippets:
            raise KeyError(f"Missing snippet for selector {selector!r}")

        # Copy begin marker line
        out.append(line)
        i += 1

        # Skip everything until end marker, then inject canonical content.
        while i < len(lines) and not _END_RE.search(lines[i]):
            i += 1

        if i >= len(lines):
            raise ValueError(f"Unclosed docgen block for selector {selector!r}")

        out.append(_render_snippet_block(snippets[snippet_id]))
        out.append(lines[i])  # end marker
        i += 1
        updated.append(selector)

    return "".join(out), updated


def check_markdown(
    markdown: str,
    *,
    snippets: dict[str, Snippet],
) -> list[str]:
    """Return a list of selectors whose embedded content differs."""
    updated, touched = update_markdown(markdown, snippets=snippets)
    mismatched: list[str] = []

    if updated == markdown:
        return mismatched

    # update_markdown always normalizes blocks; detect which ones caused changes
    # by re-checking each block in isolation.
    # Keep it simple: if any docgen blocks exist and file changed, treat all
    # touched selectors as mismatched.
    mismatched.extend(touched)
    return mismatched


def _snippet_store_payload(
    *,
    snippets: dict[str, Snippet],
    generated_at: str,
) -> dict:
    return {
        "version": 1,
        "generated_at": generated_at,
        "snippets": {
            k: {
                "id": v.id,
                "kind": v.kind,
                "language": v.language,
                "title": v.title,
                "source": v.source,
                "origin": dataclasses.asdict(v.origin),
            }
            for k, v in sorted(snippets.items())
        },
    }


def _snippet_store_json(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def write_snippet_store(
    path: Path,
    *,
    snippets: dict[str, Snippet],
    generated_at: str,
) -> None:
    payload = _snippet_store_payload(snippets=snippets, generated_at=generated_at)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_snippet_store_json(payload), encoding="utf-8")


def _iter_markdown_files(repo_root: Path, roots: list[str]) -> Iterator[Path]:
    seen: set[Path] = set()
    for root in roots:
        p = (repo_root / root).resolve()
        if p.is_file() and p.suffix.lower() == ".md":
            if p not in seen:
                seen.add(p)
                yield p
            continue
        if p.is_dir():
            for md in sorted(p.rglob("*.md")):
                if md not in seen:
                    seen.add(md)
                    yield md


def main(argv: list[str]) -> int:
    repo_root = _repo_root()

    ap = argparse.ArgumentParser(
        prog="docgen",
        description="Extract and sync docs with source code.",
    )
    ap.add_argument(
        "--snippets-out",
        default="docs/.extract/snippets.v1.json",
        help="Path to write snippet store JSON (repo-relative).",
    )
    ap.add_argument(
        "--roots",
        nargs="+",
        default=["docs"],
        help="Markdown roots to scan (files or directories, repo-relative).",
    )
    ap.add_argument("--update", action="store_true", help="Rewrite docgen blocks in-place.")
    ap.add_argument("--check", action="store_true", help="Fail if any docgen blocks are stale.")
    args = ap.parse_args(argv)

    if not args.update and not args.check:
        ap.error("Must pass --update or --check")

    index = index_fidelis_sources(repo_root=repo_root)

    md_files = list(_iter_markdown_files(repo_root, args.roots))
    all_selectors: set[str] = set()
    file_to_selectors: dict[Path, list[str]] = {}

    for md in md_files:
        text = _read_text(md)
        sels = find_docgen_selectors(text)
        if sels:
            file_to_selectors[md] = sels
            all_selectors.update(sels)

    # Build snippets only for referenced selectors.
    snippet_store = build_snippet_store(all_selectors, repo_root=repo_root, index=index)

    generated_at = _iso_utc_now()
    snippets_out = repo_root / args.snippets_out

    if args.update:
        write_snippet_store(snippets_out, snippets=snippet_store, generated_at=generated_at)
        for md, _sels in sorted(file_to_selectors.items()):
            original = _read_text(md)
            updated, _ = update_markdown(original, snippets=snippet_store)
            if updated != original:
                md.write_text(updated, encoding="utf-8")
        return 0

    # --check (read-only)
    if not snippets_out.exists():
        print(f"missing: {snippets_out.relative_to(repo_root)}", file=sys.stderr)
        return 2

    expected_payload = json.loads(snippets_out.read_text(encoding="utf-8"))
    actual_payload = _snippet_store_payload(snippets=snippet_store, generated_at=generated_at)
    if (
        expected_payload.get("version") != actual_payload.get("version")
        or expected_payload.get("snippets") != actual_payload.get("snippets")
    ):
        print(f"stale: {snippets_out.relative_to(repo_root)}", file=sys.stderr)
        return 2

    stale: list[tuple[Path, str]] = []
    for md in sorted(file_to_selectors.keys()):
        text = _read_text(md)
        mismatched = check_markdown(text, snippets=snippet_store)
        for sel in mismatched:
            stale.append((md, sel))

    if stale:
        for md, sel in stale:
            print(f"stale: {md.relative_to(repo_root)}: {sel}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""Rule 3: Libs don't import from apps."""

from __future__ import annotations

from pathlib import Path

from ._helpers import (
    APPS,
    REPO_ROOT,
    _app_names,
    _collect_imports,
    _imports_module,
    _rel,
    _src_py_files,
)


def test_libs_do_not_import_apps():
    """Dependency flows libs -> apps, never apps -> libs."""
    violations = []
    for lib_dir in (REPO_ROOT / "libs").iterdir():
        if not lib_dir.is_dir():
            continue
        for py_file in _src_py_files(lib_dir):
            collector = _collect_imports(py_file)
            for app in APPS:
                lines = _imports_module(collector.runtime_modules, app)
                for lineno in lines:
                    violations.append(f"  {_rel(py_file)}:{lineno} imports {app}")

    assert APPS, (
        "APPS derived empty — Rule 3 would pass vacuously against any lib. "
        "Fix _app_names() before trusting the green."
    )
    assert not violations, (
        "Libs must not import from apps:\n" + "\n".join(violations)
    )


def _synthetic_apps_tree(tmp_path: Path, entries: dict[str, str]) -> Path:
    """Write throwaway ``apps/`` content and return the ``apps`` directory."""
    apps = tmp_path / "apps"
    for rel, body in entries.items():
        target = apps / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
    return apps


def test_app_names_include_namespace_packages(tmp_path: Path):
    """sol HIGH r1: a PEP 420 namespace package was invisible to ``APPS``.

    ``apps/evasion/src/nsapp/feature.py`` with no ``nsapp/__init__.py`` is
    importable the moment that ``src`` is on the path, but the old
    ``(pkg / "__init__.py").is_file()`` filter dropped it from ``APPS`` — and
    an app absent from ``APPS`` is an app Rule 3 cannot see, so a lib importing
    it passed green. Missing ``__init__.py`` must cost visibility to nobody.
    """
    apps = _synthetic_apps_tree(
        tmp_path, {"evasion/src/nsapp/feature.py": "VALUE = 1\n"}
    )
    assert "nsapp" in _app_names(apps)


def test_app_names_include_underscore_packages(tmp_path: Path):
    """sol HIGH r2 §5: a single leading underscore is a legal identifier.

    ``apps/x/src/_nsapp/feature.py`` is importable as ``_nsapp.feature`` the
    moment that ``src`` is on the path. The r1 filter dropped it on a privacy
    convention that has no force at import time, taking the app out of Rule 3.
    ``__dunder__`` entries stay excluded — those really are machinery.
    """
    apps = _synthetic_apps_tree(
        tmp_path,
        {
            "x/src/_nsapp/feature.py": "VALUE = 1\n",
            "x/src/_solo.py": "VALUE = 1\n",
            "x/src/__pycache__/junk.py": "",
        },
    )
    assert _app_names(apps) == ("_nsapp", "_solo")


# Top-level directories under an app that are allowed to contain Python.
# `src` is the import root both derivations read; `tests` is never imported by
# libs and is not walked as a source root.
_APP_PYTHON_ROOTS = {"src", "tests"}

_APP_PYTHON_ROOT_EXCEPTIONS: dict[str, str] = {}


def _misplaced_app_python(apps: Path) -> list[str]:
    """Python under an app that is outside every sanctioned top-level directory.

    Containment, not existence. The predecessor only asked whether a directory
    NAMED ``src`` was present, which sol's HIGH r3 §6 defeated with the most
    ordinary partially-migrated state there is::

        apps/mixed/src/README.md        # src exists...
        apps/mixed/flatpkg/__init__.py  # ...but the Python is beside it
        apps/mixed/flatpkg/main.py

    ``_app_names`` returned ``()`` and the layout rule returned ``[]`` — the
    package sat outside both APPS and ``_source_roots``, exempt from Rule 3 and
    Rule 12, and the rule that existed to catch exactly that said nothing. An
    empty or docs-only ``src`` beside misplaced Python is not smuggling; it is
    what a half-finished migration looks like.
    """
    offenders: list[str] = []
    for app_dir in sorted(apps.iterdir()) if apps.is_dir() else []:
        if not app_dir.is_dir() or app_dir.name.startswith("."):
            continue
        for py in sorted(app_dir.rglob("*.py")):
            rel = py.relative_to(app_dir)
            parts = rel.parts
            # Excluded by shape, the same way _app_names excludes them: cache
            # dirs and dot/underscore-prefixed trees are not package layout.
            if any(p.startswith((".", "__")) for p in parts[:-1]):
                continue
            top = parts[0] if len(parts) > 1 else ""
            if top in _APP_PYTHON_ROOTS:
                continue
            if f"apps/{app_dir.name}/{top}" in _APP_PYTHON_ROOT_EXCEPTIONS:
                continue
            offenders.append(f"{app_dir.name}/{rel.as_posix()}")
    return offenders


def test_every_app_ships_python_under_a_sanctioned_root():
    """The ``src/`` layout is a RULE, and it is about CONTAINMENT.

    ``_app_names`` and Rule 12's ``_source_roots`` both derive from
    ``apps/*/src``. Python that lives anywhere else under an app is invisible
    to both: its packages never enter ``APPS``, so Rule 3 cannot see a lib
    importing them, and its sources are never walked for ``render=``/``piped``.

    r2 made the convention loud by requiring a ``src`` directory to EXIST;
    r3 showed that proves nothing about where the Python actually is. This
    asserts the property the derivations rely on — every ``.py`` under an app
    sits beneath a sanctioned top-level directory — so a half-migrated tree
    fails by naming the stray files rather than passing on the presence of an
    empty ``src``.
    """
    offenders = _misplaced_app_python(REPO_ROOT / "apps")
    assert not offenders, (
        f"app Python outside {sorted(_APP_PYTHON_ROOTS)} plus "
        f"{sorted(_APP_PYTHON_ROOT_EXCEPTIONS)}: {offenders}. Both APPS "
        "(Rule 3) and _source_roots (Rule 12) derive from apps/*/src — Python "
        "outside it is exempt from both by accident. Move it under src/, or "
        "add a reasoned exception if it is genuinely not an import root."
    )


def test_app_python_root_exceptions_are_real_and_reasoned():
    """The exception list is shrink-only in the same mechanical sense as the
    renderer allowlist: every entry must be a directory that still exists and
    must carry prose saying why it is not an import root."""
    for path, reason in _APP_PYTHON_ROOT_EXCEPTIONS.items():
        assert (REPO_ROOT / path).is_dir(), f"stale exception: {path}"
        assert reason and reason.strip(), f"{path} has no reason"


def test_src_layout_rule_catches_python_beside_an_existing_src(tmp_path: Path):
    """sol HIGH r3 §6, his fixture exactly: a ``src`` that exists but holds no
    Python, with a flat package beside it. The r2 existence check accepted this
    and the package stayed outside both derivations."""
    apps = _synthetic_apps_tree(
        tmp_path,
        {
            "mixed/src/README.md": "docs only\n",
            "mixed/flatpkg/__init__.py": "\n",
            "mixed/flatpkg/main.py": "VALUE = 1\n",
        },
    )
    assert _app_names(apps) == ()  # still invisible to the derivation
    assert _misplaced_app_python(apps) == [
        "mixed/flatpkg/__init__.py",
        "mixed/flatpkg/main.py",
    ]


def test_src_layout_rule_catches_a_flat_app(tmp_path: Path):
    """sol's r2 flat-layout construction, still caught: ``apps/x/nsapp/`` with
    no ``src`` at all."""
    apps = _synthetic_apps_tree(tmp_path, {"x/nsapp/__init__.py": "\n"})
    assert _app_names(apps) == ()
    assert _misplaced_app_python(apps) == ["x/nsapp/__init__.py"]


def test_src_layout_rule_catches_python_at_the_app_root(tmp_path: Path):
    """A bare module at the app root has no containing directory at all —
    the degenerate case the `len(parts) > 1` guard has to get right."""
    apps = _synthetic_apps_tree(tmp_path, {"x/setup_helper.py": "\n"})
    assert _misplaced_app_python(apps) == ["x/setup_helper.py"]


def test_src_layout_rule_accepts_the_sanctioned_roots(tmp_path: Path):
    """The floor. src/ and tests/ pass, and so do cache and dot-prefixed trees
    excluded by shape — otherwise the rule would fire on every checkout."""
    apps = _synthetic_apps_tree(
        tmp_path,
        {
            "x/src/pkg/__init__.py": "\n",
            "x/tests/test_pkg.py": "\n",
            "x/src/pkg/__pycache__/pkg.cpython-313.py": "\n",
            "x/.venv/lib/site.py": "\n",
        },
    )
    assert _misplaced_app_python(apps) == []


def test_src_layout_rule_ignores_apps_without_python(tmp_path: Path):
    """A docs-only or asset-only directory under apps/ is not an app skipping
    the layout, and must not be reported as one."""
    apps = _synthetic_apps_tree(tmp_path, {"notes/README.md": "hi\n"})
    assert _misplaced_app_python(apps) == []


def test_app_names_include_single_module_apps(tmp_path: Path):
    """The same hole one shape over: an app shipping a bare module, not a
    package. ``import solo`` works; the old derivation never listed it."""
    apps = _synthetic_apps_tree(tmp_path, {"tiny/src/solo.py": "VALUE = 1\n"})
    assert "solo" in _app_names(apps)


def test_app_names_exclude_build_residue(tmp_path: Path):
    """Over-approximation still has to stop at things no lib could import:
    ``*.egg-info`` build residue and dot/underscore entries."""
    apps = _synthetic_apps_tree(
        tmp_path,
        {
            "evasion/src/nsapp/feature.py": "VALUE = 1\n",
            "evasion/src/nsapp.egg-info/PKG-INFO": "Name: nsapp\n",
            "evasion/src/.hidden/x.py": "",
            "evasion/src/__pycache__/x.py": "",
        },
    )
    assert _app_names(apps) == ("nsapp",)


def test_rule3_catches_a_lib_importing_a_namespace_package_app(tmp_path: Path):
    """The evasion end to end: with ``nsapp`` restored to ``APPS``, the import
    predicate Rule 3 applies to every lib source file now fires on sol's
    ``libs/atoms/src/atoms/ratchet_evasion.py`` (``import nsapp.feature``)."""
    apps = _synthetic_apps_tree(
        tmp_path, {"evasion/src/nsapp/feature.py": "VALUE = 1\n"}
    )
    offender = tmp_path / "libs" / "atoms" / "src" / "atoms" / "ratchet_evasion.py"
    offender.parent.mkdir(parents=True, exist_ok=True)
    offender.write_text("import nsapp.feature\n")

    names = _app_names(apps)
    collector = _collect_imports(offender)
    hits = [
        (app, lineno)
        for app in names
        for lineno in _imports_module(collector.runtime_modules, app)
    ]
    assert hits == [("nsapp", 1)]

# Deployment / Release Guide

`strange-loops` is a Python **library and CLI** published to PyPI. There is no
server to deploy — "deployment" here means publishing a package and installing
the `sl`/`loops` CLI.

## Distribution model

- Published to PyPI as **`strange-loops`**.
- Consumed via `uv tool install strange-loops` or `pip install strange-loops`.
- The wheel bundles the workspace libs (`atoms`, `engine`, `lang`, `sign`,
  `store`) plus the `loops` app — see `[tool.hatch.build]` in the root
  `pyproject.toml`.
- Console scripts installed: `sl`, `sloop`, `loops` (all → `loops.main:main`).
- Rendering is a **separate** PyPI package, `painted` (`painted>=0.1.8`), pulled
  in as a runtime dependency — not vendored.

## Release process

Automated via GitHub Actions (`.github/workflows/release.yml`):

1. **Trigger:** a GitHub Release is *published* (`on: release: types:
   [published]`).
2. **Runner:** `ubuntu-latest`, environment **`pypi`**, with
   `permissions: id-token: write` (OIDC — no stored PyPI token).
3. **Steps:**
   - `actions/checkout@v4`
   - `astral-sh/setup-uv@v4` (install uv)
   - `uv build` (build sdist + wheel)
   - `pypa/gh-action-pypi-publish@release/v1` (publish via OIDC trusted
     publishing)

To cut a release: bump `version` in `pyproject.toml`, commit, then publish a
GitHub Release whose tag matches. The workflow does the rest.

## Local install for development

```bash
uv sync                 # install all workspace packages into .venv
uv tool install . -e    # install the sl/loops CLI globally (editable)
```

`uv tool install . -e` is the **production install path** — the globally
installed `sl` is what gets exercised. Per the project CLAUDE.md, after changing
CLI code, reinstall and test via `sl …` directly; the `uv run --package loops sl`
form rebuilds from source per invocation and can mask staleness of the installed
binary.

## Versioning & metadata

- **Version:** `0.3.1` (read from `pyproject.toml`).
- **Python:** requires `>=3.11`.
- **License:** MIT.
- **Build backend:** `hatchling`.

> Note: `pyproject.toml` declares `license = "MIT"` and `[tool.hatch.build]`
> lists `LICENSE` in `only-include`, but no `LICENSE` file is present at the repo
> root at time of writing — add one before the next release so it ships in the
> wheel.

## See also

- [../README.md](../README.md)
- [testing-guide.md](testing-guide.md)

---
name: release
description: >
  The strange-loops monorepo release ceremony — cut, publish, and verify a
  versioned release (CHANGELOG sweep, version stamp, wheel pre-flight, tag,
  GitHub release → PyPI trusted publishing, end-to-end deploy verification).
  Use ONLY in the loops monorepo (the repo whose root pyproject names
  `strange-loops`), when the user says "cut a release", "cut 0.X", "release
  the wave", "ship it to PyPI", or asks to tag/publish a strange-loops
  version. Not for painted (its own repo has its own process) or other
  projects.
---

# Cutting a strange-loops release

One version source: the **root** `pyproject.toml` (`strange-loops`, the flat
vendored wheel). `apps/loops`'s own version is unsynced by design — `sl
--version` reads the root dist. The publish pipeline is: annotated tag →
GitHub **release** → `.github/workflows/release.yml` (trusted publishing,
environment `pypi`, `uv build` + `pypa/gh-action-pypi-publish`, ~40s).
Creating the tag alone publishes nothing; the workflow fires on
`release: published`.

Every step below gates the next. Do not tag until the wheel pre-flight
passes; do not announce until the PyPI install smokes.

## 0. Preconditions

- The wave is merged to `main` (`--no-ff` merge per repo convention) and the
  working tree is clean. Feature branches should already be deleted or be
  deletable (`git branch -D` is fine once content is merged to HEAD — the
  local branch is often ahead of its stale remote ref).
- `CHANGELOG.md` has an `## Unreleased` section maintained during the wave.
- `git push` is multi-remote (GitLab + GitHub on one push); `gh` operates on
  the GitHub side, which is where the release workflow lives.

## 1. Gate — full suite on the exact tree you'll tag

```bash
uv sync
uv run --package loops pytest apps/loops/tests -q
for lib in $(ls libs); do
  uv run --package "$lib" pytest "libs/$lib/tests" -q
done
```

The loop iterates `libs/` rather than naming packages — a hardcoded list
goes stale the release after a new lib lands (the 0.7.0 cut had to notice
`custody` was missing from this list and run it on initiative). Every
`libs/<name>` directory is a workspace package whose name matches its
directory.

Goldens ride in the suite. If the painted pin moved this wave, this run IS
the bump gate — it must run against the exact wheel the pin resolves
(`uv pip list | grep painted` to confirm).

## 2. CHANGELOG completeness sweep

```bash
git log v<PREV>.. --oneline
```

Every **user-facing** commit gets an entry under Added / Changed / Fixed /
Removed — including merges that landed on `main` outside the wave branch
(the easy misses: a feature merged separately, dep bumps, fixes that rode
review passes). Docs-only, test-only, and skill/plugin commits skip. Write
entries from the commit messages' own vocabulary; they were written to be
quoted.

## 3. Stamp

- `## Unreleased — <wave> (X.Y.Z)` → `## X.Y.Z — YYYY-MM-DD` (keep the wave
  description as the section's intro paragraph).
- Root `pyproject.toml`: `version = "X.Y.Z"`.

## 4. Wheel pre-flight (do not skip)

The root wheel is a **flat vendored build**: hatchling inlines every
`libs/*/src`, so root `dependencies` must mirror the UNION of all libs'
third-party deps *by hand*. `uv run --package` resolves the workspace env
and therefore masks a missing union dep — only a real wheel install catches
it.

```bash
uv build
uv venv /tmp/wheel-smoke -q
uv pip install --python /tmp/wheel-smoke/bin/python dist/strange_loops-X.Y.Z-py3-none-any.whl -q
/tmp/wheel-smoke/bin/sl --version          # reports X.Y.Z
/tmp/wheel-smoke/bin/sl read project -q    # run from the repo root — reads a live store
```

If an import fails here, a lib grew a dep that never reached the root list.
Add it to root `dependencies` with a comment naming the lib, and re-run.

## 5. Release commit + tag

```bash
git add CHANGELOG.md pyproject.toml
git commit -m "release: X.Y.Z — <wave name>"   # body: what the sweep added, version bump
git tag -a vX.Y.Z -m "vX.Y.Z — <wave name>"
git push && git push origin vX.Y.Z
```

## 6. GitHub release → PyPI

Notes are the CHANGELOG section, verbatim:

```bash
awk '/^## X.Y.Z/{f=1;next} /^## <PREV>/{f=0} f' CHANGELOG.md > /tmp/relnotes.md
gh release create vX.Y.Z --title "vX.Y.Z — <wave name>" --notes-file /tmp/relnotes.md
```

Publishing fires the workflow. Watch it to completion — do not assume:

```bash
gh run watch $(gh run list --workflow=release.yml --limit 1 \
  --json databaseId -q '.[0].databaseId') --exit-status
```

If it fails on the publish step: confirm the release is *published* (not
draft), and that the `pypi` environment's trusted-publisher config still
matches the repo/workflow name.

## 7. Verify the deploy end-to-end

PyPI's index can lag the workflow by ~a minute.

```bash
curl -s https://pypi.org/pypi/strange-loops/json | python3 -c \
  "import json,sys; print(json.load(sys.stdin)['info']['version'])"   # X.Y.Z
uv venv /tmp/pypi-smoke -q
uv pip install --python /tmp/pypi-smoke/bin/python strange-loops==X.Y.Z -q
/tmp/pypi-smoke/bin/sl --version && /tmp/pypi-smoke/bin/sl read project -q
rm -rf /tmp/pypi-smoke /tmp/wheel-smoke
```

The release is not "done" until an install **from PyPI** reads a live store.

## 8. Close the loop

- `uv tool install . -e --force` — the local production `sl` back onto the
  released tree.
- Emit the release state to the project vertex: resolve or update the wave's
  thread (`sl emit project thread name=<wave-thread> status=resolved ...`)
  with commit/tag/workflow/PyPI receipts, and note what rides the next wave.
- Delete the merged wave branch (local + remote) if it survived step 0.

## Known failure modes

- **Missing union dep** — caught by step 4; the workspace runner never sees it.
- **PyPI index lag** — step 7's JSON check may trail the green workflow;
  retry before diagnosing.
- **painted/loops version collision** — the pinned painted range must have a
  published wheel; gating against a local painted checkout proves nothing
  about the PyPI resolve (re-gate when the pin's target ships).
- **Tag without release** — a pushed tag alone never publishes; the workflow
  triggers on the GitHub release event.

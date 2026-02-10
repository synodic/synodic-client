# Python Bootstrap Example

This example demonstrates using Porringer to bootstrap a complete Python
development environment from scratch — the same chain a developer would
follow manually.

## Bootstrap Chain

The manifest executes in **phased order**:

1. **`runtimes.python`** → installs Python 3.14 via `pim` (Windows) or
   `pyenv` (macOS / Linux).  The resolved interpreter path is propagated
   to all downstream phases.
2. **`packages.python`** → installs `pipx` into the current Python
   environment via `pip` or `uv`.
3. **`tools.python`** → installs `pdm` as an isolated CLI tool via
   `pipx`.  The pipx backend is **deferred** at preview time — it becomes
   available only after Phase 2 installs it.
4. **`post_sync`** → runs `pdm install` in the manifest directory,
   creating the project virtualenv and installing all dependencies from
   `pyproject.toml`.

## Manifest Overview

```text
runtimes.python  ─►  pim / pyenv   ─►  Python 3.14
packages.python  ─►  pip / uv      ─►  pipx
tools.python     ─►  pipx          ─►  pdm          (deferred resolution)
post_sync        ─►  pdm install                    (project sync)
```

## Usage

### Preview what will happen

```shell
porringer sync --path examples/python-bootstrap --dry-run
```

### Execute with confirmation

```shell
porringer sync --path examples/python-bootstrap
```

### Execute without confirmation (non-interactive)

```shell
porringer sync --path examples/python-bootstrap --yes
```

## How It Works

Porringer's execution engine splits `PACKAGE`-type actions into sub-phases:

- **Phase 1 (Runtime):** Runtime providers (pim / pyenv) run first.  The
  resolved interpreter is forwarded to all `RuntimeConsumer` plugins so
  that subsequent pip / uv commands target the correct Python.
- **Phase 2a (Package):** Regular package installs (pip / uv).  This is
  where pipx gets installed.
- **Phase 2b (Tool):** After Phase 2a the engine **re-discovers**
  available plugins.  Pipx is now on PATH, so the `tools.python` section
  resolves to the pipx backend and pdm is installed.
- **Phase 3 (Project Sync):** Project-environment plugins (pdm, uv,
  poetry) run their native sync / install command.
- **Phase 4 (Post-sync):** Arbitrary shell commands execute in the
  manifest directory.

If a tool backend is not available at preview time (e.g. pipx is not yet
installed), the action is created with a *deferred* installer.  Resolution
happens just before Phase 2b, after packages have been installed.

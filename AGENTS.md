# AGENTS.md

An application frontend for [porringer](https://www.github.com/synodic/porringer) that manages and downloads package managers and their dependents.

We use [PDM](https://pdm-project.org/en/latest/) as our build system and package manager. All commands below are `pdm <script>`.

## Quick Commands

| Command | Description |
|---------|-------------|
| `pdm dev` | Launch the app from source with `--dev` isolation. Accepts `-- --debug` for verbose file logging. |
| `pdm test` | Run pytest with coverage (`--cov=synodic_client`). |
| `pdm lint` | Composite: `analyze` + `format` + `type-check`. |
| `pdm analyze` | `ruff check` — linting only. |
| `pdm format` | `ruff format` — formatting only. |
| `pdm type-check` | `pyrefly check` — type checking. |

`post_install` runs automatically after `pdm install` and registers example project directories with porringer.

## Dev Mode

The `--dev` flag isolates the development instance from production:

- **Config dir:** `%LOCALAPPDATA%\Synodic-Dev\` (instead of `Synodic\`)
- **Log file:** `synodic-dev.log` (instead of `synodic.log`)
- **Instance lock:** Separate named socket — dev and production can run side-by-side.
- **Velopack + protocol registration:** Skipped in dev mode.

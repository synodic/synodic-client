# Development Guide

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

## Debug CLI

With the app running (`pdm dev`), inspect and control it from another terminal:

```shell
pdm run synodic-c debug state --dev              # JSON dump of app state, config, update phase, data
pdm run synodic-c debug actions --dev            # List available actions with descriptions
pdm run synodic-c debug action <name> --dev      # Trigger an action (e.g. check_update, show_main)
pdm run synodic-c debug action <name> <arg> --dev  # Action with argument (e.g. add_project /path)
```

Available actions: `check_update`, `tool_update`, `refresh_data`, `show_main`, `show_settings`, `apply_update`, `list_projects`, `add_project`, `remove_project`, `project_status`, `select_project`.

### Project management actions

| Action | Arg | Description |
|--------|-----|-------------|
| `list_projects` | — | List cached directories with validation status. |
| `add_project` | `<path>` | Add a directory to the cache (no file picker). |
| `remove_project` | `<path>` | Remove a directory from the cache. |
| `project_status` | `[path]` | Per-action preview status. Defaults to selected project. |
| `select_project` | `<path>` | Switch sidebar selection to a project. |

Example workflow:

```shell
pdm run synodic-c debug action list_projects --dev
pdm run synodic-c debug action show_main --dev
pdm run synodic-c debug action project_status --dev                # selected project
pdm run synodic-c debug action project_status D:\example --dev     # specific project
pdm run synodic-c debug action add_project D:\my-project --dev
pdm run synodic-c debug action remove_project D:\my-project --dev
```

Commands route to the controller/service layer (not widgets), so they are stable across UI changes.

For production instances, omit `--dev`:

```shell
pdm run synodic-c debug state
pdm run synodic-c debug action check_update
```

## IPC Console

The debug CLI communicates with the running GUI over a local named-pipe IPC channel powered by `QLocalServer` / `QLocalSocket` (PySide6).

### Architecture

```
CLI process                             GUI process
───────────                             ───────────
synodic-c debug <cmd>
  │
  ▼
SingleInstance.send_debug_command(cmd)
  │  connects to named pipe
  │  writes  b"debug:<cmd>"
  │  waits for response
  │                                     QLocalServer._on_new_connection()
  │                                       reads "debug:<cmd>"
  │                                       strips prefix → DebugHandler.handle(cmd)
  │                                       returns JSON string
  ▼
  reads JSON response
  pretty-prints to stdout
```

### Transport

| Detail | Value |
|--------|-------|
| Server name | `synodic-client` (production) / `synodic-client-dev` (dev mode) |
| Backing | Windows named pipe (`\\.\pipe\…`), Unix domain socket elsewhere |
| Protocol | `debug:` prefix → synchronous JSON response; all other payloads treated as `synodic://` URIs (fire-and-forget) |

### Wiring

1. **Server start** — `SingleInstance.start_server()` opens the `QLocalServer` during GUI init in `application/qt.py`.
2. **Handler registration** — `SingleInstance.set_debug_handler(debug_handler.handle)` connects the `DebugHandler` callback.
3. **Client send** — Each CLI invocation calls `SingleInstance.send_debug_command(command)`, which opens a new socket, writes the prefixed message, reads the JSON response, and disconnects.

Dev and production instances use separate server names so they can run side-by-side without colliding.

### Key files

| File | Role |
|------|------|
| `synodic_client/application/instance.py` | `SingleInstance` — QLocalServer/QLocalSocket transport, `send_debug_command()` static helper |
| `synodic_client/application/debug.py` | `DebugHandler` — dispatches commands to controllers, returns JSON |
| `synodic_client/cli/debug.py` | CLI subcommands (`state`, `actions`, `action`) that call `_send_debug()` |
| `synodic_client/application/qt.py` | Wires `SingleInstance` + `DebugHandler` during startup |

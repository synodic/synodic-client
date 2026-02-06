# Python Development Environment Example

This example demonstrates using Porringer to set up a Python development environment with common linting, formatting, and testing tools.

## Manifest Overview

The `porringer.json` manifest defines:

- **Prerequisites**: Ensures essential plugins are available
  - `pip` and `pipx` - Always required for Python package management
  - `winget` - Required on Windows to support native tool discovery
  - `apt` - Required on Linux for native package management
  - `brew` - Required on macOS for native package management
- **pip packages**: Development tools installed in the current environment
  - `ruff` - Fast Python linter and formatter
  - `pyrefly` - Static type checker
  - `pytest` - Testing framework
  - `pytest-cov` - Coverage plugin for pytest
- **pipx packages**: CLI tools installed in isolated environments
  - `pdm` - Python project manager

## Usage

### Preview what will happen

```shell
porringer install --path examples/python-dev --dry-run
```

### Execute with confirmation

```shell
porringer install --path examples/python-dev
```

### Execute without confirmation (non-interactive)

```shell
porringer install --path examples/python-dev --yes
```

## Platform-Specific Prerequisites

The manifest automatically filters prerequisites based on your platform:

| Platform   | Checked Prerequisites |
|------------|----------------------|
| Windows    | pip, pipx, winget    |
| Linux      | pip, pipx, apt       |
| macOS      | pip, pipx, brew      |

## Alternative: pyproject.toml

You can also embed this manifest in a `pyproject.toml` file:

```toml
[tool.porringer]
version = "1"

[[tool.porringer.prerequisites]]
plugin = "pip"

[[tool.porringer.prerequisites]]
plugin = "pipx"

[[tool.porringer.prerequisites]]
plugin = "winget"
platforms = ["win32"]

[[tool.porringer.prerequisites]]
plugin = "apt"
platforms = ["linux"]

[[tool.porringer.prerequisites]]
plugin = "brew"
platforms = ["darwin"]

[tool.porringer.packages]
pip = ["ruff", "pyrefly", "pytest", "pytest-cov"]
pipx = ["pdm"]
```

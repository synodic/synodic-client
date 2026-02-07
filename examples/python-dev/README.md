# Python Development Environment Example

This example demonstrates using Porringer to set up a Python development environment with common linting, formatting, and testing tools.

## Manifest Overview

The `porringer.json` manifest defines:

- **Metadata**: Display information for GUI consumers (install preview)
  - `name` - Human-readable project name
  - `description` - Short description shown in the install preview header
  - `author` - Author or organization name
  - `url` - Project URL for reference
- **Prerequisites**: Ensures essential plugins are available
  - `pip` and `pipx` - Always required for Python package management
  - `winget` - Required on Windows to support native tool discovery
  - `apt` - Required on Linux for native package management
  - `brew` - Required on macOS for native package management
- **pip packages**: Development tools installed in the current environment
  - `ruff>=0.8.0` - Fast Python linter and formatter (with version constraint)
  - `pyrefly` - Static type checker
  - `pytest>=9.0` - Testing framework (with version constraint)
  - `pytest-cov` - Coverage plugin for pytest
- **pipx packages**: CLI tools installed in isolated environments
  - `pdm` - Python project manager

Packages can be specified as plain strings (`"ruff"`) or as objects with optional `description` and `platforms` fields. Version constraints use PEP 440 syntax (e.g., `"ruff>=0.8.0"`, `"pydantic>=2,<3"`).

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

### Upgrade existing packages

```shell
porringer install --path examples/python-dev --mode upgrade
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
name = "Python Dev Environment"
description = "Common linting, formatting, and testing tools"
author = "Synodic Software"
url = "https://github.com/synodic/porringer"

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
pip = ["ruff>=0.8.0", "pyrefly", "pytest>=9.0", "pytest-cov"]
pipx = ["pdm"]
```

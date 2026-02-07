# Python Development Environment Example

This example demonstrates using Porringer to set up a Python development environment with common linting, formatting, and testing tools.

## Manifest Overview

The `porringer.json` manifest declares the desired **state** using backend identifiers. Porringer resolves each backend to the best available installer at runtime.

- **`python` backend** (resolved to `uv` or `pip`): Development tools installed in the current environment
  - `ruff` - Fast Python linter and formatter
  - `pyrefly` - Python type checker
  - `pytest` - Testing framework
  - `pytest-cov` - Coverage plugin for pytest
- **`python-tool` backend** (resolved to `pipx`): CLI tools installed in isolated environments
  - `pdm` - Python package and dependency manager

Packages can be specified as plain strings (`"pytest"`) or as objects with optional `description` and `platforms` fields. Version constraints use PEP 440 syntax (e.g., `"ruff>=0.8.0"`, `"pydantic>=2,<3"`).

## Usage

### Preview what will happen

```shell
porringer sync --path examples/python-dev --dry-run
```

### Execute with confirmation

```shell
porringer sync --path examples/python-dev
```

### Execute without confirmation (non-interactive)

```shell
porringer sync --path examples/python-dev --yes
```

### Upgrade all packages to latest

```shell
porringer sync --path examples/python-dev --strategy latest
```

## Alternative: pyproject.toml

You can also embed this manifest in a `pyproject.toml` file:

```toml
[tool.porringer]
version = "1"

[tool.porringer.state]
python = ["ruff", "pyrefly", "pytest", "pytest-cov"]
python-tool = ["pdm"]

[tool.porringer.preferences]
python = "uv"  # optional: prefer uv over pip
```

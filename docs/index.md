# Synodic Client

An application frontend for [porringer](https://www.github.com/synodic/porringer) that helps manage and download package managers and their dependents.

## Features

- **System Tray Application**: Runs unobtrusively in the system tray
- **Secure Self-Updates**: Automatic updates using [Velopack](https://velopack.io/) for seamless installation and delta updates
- **Multiple Update Channels**: Support for stable releases and development prereleases
- **Cross-Platform**: Windows, macOS, and Linux support

## Installation

```bash
pip install synodic-client
```

Or with PDM:

```bash
pdm add synodic-client
```

## Quick Start

Launch the application:

```bash
synodic-c
```

Or with a `synodic://` URI:

```bash
synodic-c "synodic://install?manifest=https://example.com/porringer.json"
```

Show the version:

```bash
synodic-c --version
```

The application runs in the system tray. Right-click the tray icon to access:

- **Open** - Show the main window
- **Settings** - Configure application settings
- **Check for Updates...** - Manually check for and install updates
- **Quit** - Exit the application

## Documentation

- [Self-Update System](updates.md) - How automatic updates work
- [Development Guide](development.md) - Contributing and building from source

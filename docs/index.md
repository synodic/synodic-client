# Synodic Client

An application frontend for [porringer](https://www.github.com/synodic/porringer) that helps manage and download package managers and their dependents.

## Features

- **System Tray Application**: Runs unobtrusively in the system tray
- **Secure Self-Updates**: Automatic updates using [TUF](https://theupdateframework.io/) for cryptographic verification
- **Multiple Update Channels**: Support for stable releases and development prereleases
- **Rollback Support**: Automatic backup and rollback on update failure

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
synodic-client
```

The application runs in the system tray. Right-click the tray icon to access:

- **Open** - Show the main window
- **Settings** - Configure application settings
- **Check for Updates...** - Manually check for and install updates
- **Quit** - Exit the application

## Documentation

- [Self-Update System](updates.md) - How automatic updates work
- [Development Guide](development.md) - Contributing and building from source

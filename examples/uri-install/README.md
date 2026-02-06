# URI Install Example

This example demonstrates the `synodic://` URI protocol for triggering a Porringer manifest install from a link.

[![Install with Synodic](https://img.shields.io/badge/Install_with-Synodic_Client-5865F2?style=for-the-badge&logo=windowsterminal&logoColor=white)](synodic://install?manifest=https://raw.githubusercontent.com/synodic/porringer/development/examples/python-dev/porringer.json)

> **Note:** The badge link uses the `synodic://` protocol. It will only work on
> systems with the Synodic Client installed and the protocol handler registered.
> GitHub strips custom protocol links — copy the URI below to test manually.

## URI

```
synodic://install?manifest=https://raw.githubusercontent.com/synodic/porringer/development/examples/python-dev/porringer.json
```

Clicking or invoking the URI above launches the Synodic Client and opens the install preview for the [python-dev](../python-dev/) manifest.

## How it works

The `synodic://` protocol is registered as a URI handler on the system.  When the
OS resolves the link it launches:

```
synodic.exe "synodic://install?manifest=https://raw.githubusercontent.com/synodic/porringer/development/examples/python-dev/porringer.json"
```

The client parses the URI into:

| Component    | Value |
|--------------|-------|
| **action**   | `install` |
| **manifest** | `https://raw.githubusercontent.com/synodic/porringer/development/examples/python-dev/porringer.json` |

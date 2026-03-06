# AGENTS.md

This repository doesn't contain any agent specific instructions other than its [README.md](README.md), required development documentation, and its linked resources.

## Logging

Application logs are written to a deterministic path under the OS config directory:

| Mode           | Path                                                 |
|----------------|------------------------------------------------------|
| Production     | `%LOCALAPPDATA%\Synodic\logs\synodic.log`            |
| Dev (`--dev`)  | `%LOCALAPPDATA%\Synodic-Dev\logs\synodic-dev.log`    |

Resolve the current log path programmatically:

```shell
python -c "from synodic_client.logging import log_path; print(log_path())"
```

Logs use rotating file handlers (1 MB max, 3 backups).

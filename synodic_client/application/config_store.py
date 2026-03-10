"""Centralized configuration store.

Provides a single source of truth for :class:`ResolvedConfig` so that
every consumer (ToolsView, SettingsWindow, UpdateController,
ToolUpdateOrchestrator) always reads the same snapshot and receives
change notifications through a Qt signal.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from synodic_client.resolution import ResolvedConfig, resolve_config, update_user_config


class ConfigStore(QObject):
    """Observable wrapper around :class:`ResolvedConfig`.

    All config mutations go through :meth:`update` (which persists to
    disk) or :meth:`set` (which replaces without persisting).  Both
    emit :attr:`changed` so every connected consumer stays in sync.

    Typical usage::

        store = ConfigStore(initial_config)
        store.changed.connect(some_consumer.on_config_changed)
        store.update(auto_apply=False)   # persists + emits
    """

    changed = Signal(object)
    """Emitted with the new ``ResolvedConfig`` after every mutation."""

    def __init__(self, config: ResolvedConfig | None = None, parent: QObject | None = None) -> None:
        """Create a new store, optionally seeded with *config*."""
        super().__init__(parent)
        self._config = config if config is not None else resolve_config()

    @property
    def config(self) -> ResolvedConfig:
        """The current configuration snapshot."""
        return self._config

    def update(self, **changes: object) -> ResolvedConfig:
        """Persist *changes* to disk and broadcast the new config.

        Wraps :func:`~synodic_client.resolution.update_user_config`.

        Args:
            **changes: Field-name / value pairs forwarded to
                :func:`update_user_config`.

        Returns:
            The fresh :class:`ResolvedConfig`.
        """
        self._config = update_user_config(**changes)
        self.changed.emit(self._config)
        return self._config

    def set(self, config: ResolvedConfig) -> None:
        """Replace the config without persisting and notify listeners.

        Use for externally resolved configs (e.g. passed at startup).
        """
        self._config = config
        self.changed.emit(self._config)

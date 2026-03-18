"""Configuration operations.

Pure functions for reading, writing, and introspecting configuration.
No Qt, no signals — works with the resolution module directly.
"""

from __future__ import annotations

import dataclasses

from synodic_client.operations.schema import ConfigKeyInfo
from synodic_client.resolution import resolve_config, update_user_config
from synodic_client.schema import ResolvedConfig


def get_config() -> ResolvedConfig:
    """Load and return the current resolved configuration.

    Returns:
        An immutable :class:`ResolvedConfig` snapshot.
    """
    return resolve_config()


def get_config_value(key: str) -> object:
    """Read a single configuration key.

    Args:
        key: The :class:`ResolvedConfig` field name.

    Returns:
        The current value of the field.

    Raises:
        KeyError: If *key* is not a recognised config field.
    """
    valid_keys = {f.name for f in dataclasses.fields(ResolvedConfig)}
    if key not in valid_keys:
        msg = f'Unknown config key: {key!r}. Valid keys: {sorted(valid_keys)}'
        raise KeyError(msg)

    config = resolve_config()
    return getattr(config, key)


def set_config(key: str, value: object) -> ResolvedConfig:
    """Update a single configuration key and return the new config.

    Args:
        key: The :class:`UserConfig` field name.
        value: The new value.

    Returns:
        The updated :class:`ResolvedConfig`.

    Raises:
        KeyError: If *key* is not a recognised config field.
    """
    valid_keys = {f.name for f in dataclasses.fields(ResolvedConfig)}
    if key not in valid_keys:
        msg = f'Unknown config key: {key!r}. Valid keys: {sorted(valid_keys)}'
        raise KeyError(msg)

    return update_user_config(**{key: value})


def update_config(**changes: object) -> ResolvedConfig:
    """Persist multiple configuration changes and return the new config.

    Each key is validated against :class:`ResolvedConfig` fields before
    writing.  This is the batch equivalent of :func:`set_config`.

    Args:
        **changes: Field-name / value pairs.

    Returns:
        The updated :class:`ResolvedConfig`.

    Raises:
        KeyError: If any key is not a recognised config field.
    """
    valid_keys = {f.name for f in dataclasses.fields(ResolvedConfig)}
    for key in changes:
        if key not in valid_keys:
            msg = f'Unknown config key: {key!r}. Valid keys: {sorted(valid_keys)}'
            raise KeyError(msg)
    return update_user_config(**changes)


def list_config_keys(config: ResolvedConfig | None = None) -> dict[str, ConfigKeyInfo]:
    """Return metadata for every configuration key.

    Args:
        config: Optional resolved config to read current values from.
            If ``None``, a fresh config is loaded.

    Returns:
        A dict mapping field name → :class:`ConfigKeyInfo`.
    """
    if config is None:
        config = resolve_config()

    result: dict[str, ConfigKeyInfo] = {}
    for f in dataclasses.fields(ResolvedConfig):
        result[f.name] = ConfigKeyInfo(
            name=f.name,
            type_hint=str(f.type),
            description='',
            current_value=getattr(config, f.name),
        )
    return result

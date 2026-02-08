"""Centralised UI constants, sizes, and style fragments.

Collecting magic numbers and inline stylesheets here keeps the widget
code focused on layout and behaviour rather than pixel tweaking.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Window sizes (width, height)
# ---------------------------------------------------------------------------
INSTALL_PREVIEW_MIN_SIZE = (650, 400)
MAIN_WINDOW_MIN_SIZE = (600, 400)
UPDATE_SOURCE_DIALOG_MIN_WIDTH = 450

# ---------------------------------------------------------------------------
# Layout margins (left, top, right, bottom)
# ---------------------------------------------------------------------------
CONTENT_MARGINS = (12, 12, 12, 12)
COMPACT_MARGINS = (8, 8, 8, 8)
NO_MARGINS = (0, 0, 0, 0)

# ---------------------------------------------------------------------------
# Timers / durations (milliseconds)
# ---------------------------------------------------------------------------
COPY_FEEDBACK_MS = 1200
"""How long the copy-button shows a ✓ before reverting."""

SOCKET_TIMEOUT_MS = 1000
"""Timeout used by :class:`SingleInstance` socket operations."""

# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
MONOSPACE_FAMILY = 'Consolas'
MONOSPACE_SIZE = 10

# ---------------------------------------------------------------------------
# Copy button
# ---------------------------------------------------------------------------
COPY_ICON = '\U0001f4cb'
COPY_BTN_SIZE = (28, 28)
COPY_BTN_STYLE = (
    'QToolButton { border: none; padding: 2px 4px; }'
    'QToolButton:hover { background: palette(midlight); border-radius: 3px; }'
)

# ---------------------------------------------------------------------------
# Stylesheet fragments
# ---------------------------------------------------------------------------
HEADER_STYLE = 'font-size: 14px; font-weight: bold;'
MUTED_STYLE = 'color: grey;'
COMMAND_HEADER_STYLE = 'color: grey; margin-top: 6px;'

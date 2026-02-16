"""Centralised UI constants, sizes, and style fragments.

Collecting magic numbers and inline stylesheets here keeps the widget
code focused on layout and behaviour rather than pixel tweaking.
"""

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

# ---------------------------------------------------------------------------
# Execution log panel
# ---------------------------------------------------------------------------

# Section header styles
LOG_SECTION_HEADER_STYLE = (
    'QWidget#sectionHeader {'
    '  background: palette(midlight);'
    '  border: 1px solid palette(mid);'
    '  border-radius: 3px;'
    '  padding: 4px 8px;'
    '}'
)
LOG_CHEVRON_STYLE = 'font-size: 10px; color: palette(text);'
LOG_SECTION_TITLE_STYLE = 'font-weight: bold; font-size: 12px;'

# Status badge colours
LOG_STATUS_RUNNING = 'color: #3794ff;'
"""Blue — action is currently executing."""

LOG_STATUS_SUCCESS = 'color: #89d185;'
"""Green — action completed successfully."""

LOG_STATUS_FAILED = 'color: #f48771;'
"""Red-orange — action failed."""

LOG_STATUS_SKIPPED = 'color: grey;'
"""Grey — action was skipped."""

# Output text colours (used in HTML spans inside QTextEdit)
LOG_COLOR_STDOUT = '#d4d4d4'
"""Default text — stdout lines."""

LOG_COLOR_STDERR = '#d7ba7d'
"""Amber — stderr lines."""

LOG_COLOR_PHASE = '#808080'
"""Grey — phase/status messages."""

LOG_COLOR_ERROR = '#f48771'
"""Red-orange — error messages."""

LOG_COLOR_SUCCESS = '#89d185'
"""Green — success messages."""

# Output area style
LOG_OUTPUT_STYLE = (
    'QTextEdit {'
    '  background: #1e1e1e;'
    '  border: 1px solid palette(mid);'
    '  border-top: none;'
    '  border-bottom-left-radius: 3px;'
    '  border-bottom-right-radius: 3px;'
    '  padding: 6px;'
    '}'
)

# ---------------------------------------------------------------------------
# Plugin section panel
# ---------------------------------------------------------------------------
PLUGIN_GROUP_HEADER_STYLE = 'QWidget#pluginGroupHeader {  padding: 6px 4px 2px 0px;}'
"""Style for the collapsible group header in the plugins view."""

PLUGIN_GROUP_TITLE_STYLE = 'font-weight: bold; font-size: 13px;'
"""Style for the group heading label text."""

PLUGIN_GROUP_SECTION_SPACING = 2
"""Pixels between plugin sections within a group."""

PLUGIN_SECTION_HEADER_STYLE = (
    'QWidget#pluginHeader {'
    '  background: palette(midlight);'
    '  border: 1px solid palette(mid);'
    '  border-radius: 3px;'
    '  padding: 4px 8px;'
    '}'
)
PLUGIN_TOGGLE_STYLE = (
    'QPushButton { padding: 2px 8px; border: 1px solid palette(mid); border-radius: 3px;'
    '  min-width: 60px; max-width: 60px; }'
    'QPushButton:checked { background: #89d185; color: black; }'
    'QPushButton:disabled { color: palette(mid); border-color: palette(mid); background: transparent; }'
    'QPushButton:checked:disabled { background: transparent; color: palette(mid); }'
)

PLUGIN_UPDATE_STYLE = (
    'QPushButton { padding: 2px 8px; border: 1px solid palette(mid); border-radius: 3px;'
    '  min-width: 60px; max-width: 60px; }'
    'QPushButton:disabled { color: palette(mid); border-color: palette(mid); background: transparent; }'
)
PLUGIN_SECTION_SPACING = 4
"""Pixels between plugin sections in the scroll area."""

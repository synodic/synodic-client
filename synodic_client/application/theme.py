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

# ---------------------------------------------------------------------------
# Card-based layout
# ---------------------------------------------------------------------------
CARD_FRAME_STYLE = (
    'QFrame#card {  border: 1px solid palette(mid);  border-radius: 6px;  background: palette(window);  padding: 8px;}'
)
"""Rounded card frame style used for layout sections."""

CARD_HEADER_STYLE = 'font-weight: bold; font-size: 12px; margin-bottom: 4px;'
"""Style for a card title label."""

CARD_SPACING = 8
"""Pixels between cards in a grid or box layout."""

# ---------------------------------------------------------------------------
# Action card (install screen)
# ---------------------------------------------------------------------------
ACTION_CARD_STYLE = (
    'QFrame#actionCard {'
    '  border: 1px solid palette(mid);'
    '  border-radius: 4px;'
    '  background: palette(window);'
    '  padding: 6px 8px;'
    '}'
)
"""Default style for an action card in the install preview."""

ACTION_CARD_EXECUTING_STYLE = (
    'QFrame#actionCard {'
    '  border: 1px solid #3794ff;'
    '  border-radius: 4px;'
    '  background: palette(window);'
    '  padding: 6px 8px;'
    '}'
)
"""Style for an action card that is currently executing."""

ACTION_CARD_SKELETON_STYLE = (
    'QFrame#actionCard {'
    '  border: 1px solid palette(mid);'
    '  border-radius: 4px;'
    '  background: palette(midlight);'
    '  padding: 6px 8px;'
    '}'
)
"""Muted style for skeleton/placeholder action cards."""

ACTION_CARD_SPACING = 4
"""Pixels between action cards in the list."""

ACTION_CARD_TYPE_BADGE_STYLE = (
    'QLabel { font-size: 10px; font-weight: bold;'
    '  padding: 1px 6px; border-radius: 3px;'
    '  background: palette(midlight); color: palette(text); }'
)
"""Small type badge (Package, Tool, Runtime, etc.) on each action card."""

ACTION_CARD_PACKAGE_STYLE = 'font-weight: bold; font-size: 12px;'
"""Primary line: package name."""

ACTION_CARD_DESC_STYLE = 'color: grey; font-size: 11px;'
"""Secondary line: description text."""

ACTION_CARD_VERSION_STYLE = 'font-size: 11px;'
"""Version transition text."""

ACTION_CARD_STATUS_CHECKING = 'color: grey; font-size: 11px;'
"""Status label: Checking…"""

ACTION_CARD_STATUS_NEEDED = 'color: palette(text); font-size: 11px; font-weight: bold;'
"""Status label: Needed."""

ACTION_CARD_STATUS_SATISFIED = 'color: grey; font-size: 11px;'
"""Status label: Already installed."""

ACTION_CARD_STATUS_UPDATE = 'color: #d7ba7d; font-size: 11px; font-weight: bold;'
"""Status label: Update available (amber)."""

ACTION_CARD_STATUS_UNAVAILABLE = 'color: #f48771; font-size: 11px;'
"""Status label: Plugin not installed (red-orange)."""

ACTION_CARD_STATUS_RUNNING = 'color: #3794ff; font-size: 11px; font-weight: bold;'
"""Status label: Running… (blue)."""

ACTION_CARD_STATUS_DONE = 'color: #89d185; font-size: 11px; font-weight: bold;'
"""Status label: Done (green)."""

ACTION_CARD_STATUS_FAILED = 'color: #f48771; font-size: 11px; font-weight: bold;'
"""Status label: Failed (red-orange)."""

ACTION_CARD_STATUS_SKIPPED = 'color: grey; font-size: 11px;'
"""Status label: Skipped."""

ACTION_CARD_LOG_STYLE = (
    'QTextEdit {'
    '  background: #1e1e1e;'
    '  border: 1px solid palette(mid);'
    '  border-radius: 3px;'
    '  padding: 4px;'
    '  margin-top: 4px;'
    '}'
)
"""Inline log output area within an action card."""

ACTION_CARD_SKELETON_BAR_STYLE = 'QFrame { background: palette(mid); border-radius: 2px; }'
"""Placeholder bar used inside skeleton action cards."""

ACTION_CARD_COMMAND_STYLE = 'color: grey; font-size: 10px; font-family: Consolas, monospace;'
"""Muted monospace line showing the CLI command on each action card."""

ACTION_CARD_SPINNER_SIZE = 12
"""Diameter (px) of the per-card inline checking spinner."""

ACTION_CARD_SPINNER_PEN = 2
"""Pen width (px) for the per-card inline spinner arc."""

# ---------------------------------------------------------------------------
# Metadata skeleton card
# ---------------------------------------------------------------------------
METADATA_SKELETON_HEIGHT = 72
"""Fixed height for the metadata skeleton card shown during loading."""

METADATA_SKELETON_STYLE = (
    'QFrame#card {'
    '  border: 1px solid palette(mid);'
    '  border-radius: 6px;'
    '  background: palette(midlight);'
    '  padding: 8px;'
    '}'
)
"""Muted card frame used as the metadata placeholder during loading."""

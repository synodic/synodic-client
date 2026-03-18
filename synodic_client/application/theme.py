"""Centralised UI constants, sizes, and style fragments.

Collecting magic numbers and inline stylesheets here keeps the widget
code focused on layout and behaviour rather than pixel tweaking.
"""

# ---------------------------------------------------------------------------
# Window sizes (width, height)
# ---------------------------------------------------------------------------
INSTALL_PREVIEW_MIN_SIZE = (650, 400)
MAIN_WINDOW_MIN_SIZE = (900, 600)

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
LOADING_LABEL_STYLE = 'color: grey; font-size: 13px;'
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
# Plugin panel — modernised flat list
# ---------------------------------------------------------------------------

# Kind header — uppercase section divider ("TOOLS", "PACKAGES", …)
PLUGIN_KIND_HEADER_STYLE = (
    'QLabel#pluginKindHeader {'
    '  font-size: 11px;'
    '  font-weight: bold;'
    '  color: #808080;'
    '  text-transform: uppercase;'
    '  padding: 10px 4px 4px 4px;'
    '  border-bottom: 1px solid palette(mid);'
    '}'
)
"""Uppercase, muted section divider for each plugin-kind group."""

PLUGIN_KIND_HEADER_SPACING = 6
"""Pixels below a kind header before the first provider row."""

# Provider sub-header — thin row showing the managing plugin
PLUGIN_PROVIDER_STYLE = 'QFrame#pluginProvider {  background: transparent;  padding: 2px 8px 2px 4px;}'
"""Subtle sub-header row for the plugin that manages a set of tools."""

PLUGIN_PROVIDER_NAME_STYLE = 'font-size: 12px; font-weight: bold; color: #cccccc;'
"""Provider name (e.g. "uv", "pip")."""

PLUGIN_PROVIDER_VERSION_STYLE = 'font-size: 11px; color: #808080;'
"""Provider version text."""

PLUGIN_PROVIDER_STATUS_INSTALLED_STYLE = 'font-size: 10px; color: #89d185;'
"""Green dot / label for installed providers."""

PLUGIN_PROVIDER_STATUS_MISSING_STYLE = 'font-size: 10px; color: #f48771;'
"""Red-orange dot / label for missing providers."""

PLUGIN_PROVIDER_RUNTIME_TAG_STYLE = (
    'QLabel { font-size: 10px; color: #7fb3e0; background: #1e3a5f;  border-radius: 8px; padding: 1px 6px; }'
)
"""Pill-shaped runtime tag for per-runtime provider headers."""

PLUGIN_PROVIDER_RUNTIME_TAG_DEFAULT_STYLE = (
    'QLabel { font-size: 10px; color: #89d185; background: #1e3a2f;  border-radius: 8px; padding: 1px 6px; }'
)
"""Pill-shaped runtime tag highlighted for the default runtime."""

# Compact tool / package row
PLUGIN_ROW_STYLE = (
    'QFrame#pluginRow {'
    '  background: transparent;'
    '  border-radius: 4px;'
    '  padding: 3px 8px 3px 20px;'
    '}'
    'QFrame#pluginRow:hover {'
    '  background: #2a2d2e;'
    '}'
)
"""Compact row for an individual tool or package managed by a plugin."""

PLUGIN_ROW_HIGHLIGHT_STYLE = (
    'QFrame#pluginRow {  background: #3e3417;  border-radius: 4px;  padding: 3px 8px 3px 20px;}'
)
"""Brief amber highlight applied when navigating to a specific package row."""

PLUGIN_ROW_NAME_STYLE = 'font-size: 12px; color: #cccccc;'
"""Package / tool name in a row."""

PLUGIN_ROW_PROJECT_STYLE = 'font-size: 11px; color: #808080;'
"""Project directory association in a row."""

PLUGIN_ROW_VERSION_STYLE = 'font-size: 11px; color: grey;'
"""Version text in a row."""

PLUGIN_ROW_GLOBAL_STYLE = 'font-size: 11px; color: #808080; font-style: italic;'
"""Muted italic annotation label for non-manifest (global) packages."""

PLUGIN_ROW_HOST_STYLE = 'font-size: 11px; color: #808080;'
"""Host-tool annotation label (e.g. "→ pdm") for injected packages."""

PLUGIN_ROW_TOGGLE_STYLE = (
    'QPushButton { padding: 1px 4px; border: 1px solid palette(mid); border-radius: 2px;'
    '  font-size: 10px; min-width: 36px; max-width: 36px; }'
    'QPushButton:checked { background: #89d185; color: black; }'
    'QPushButton:disabled { color: palette(mid); border-color: palette(mid); background: transparent; }'
    'QPushButton:checked:disabled { background: transparent; color: palette(mid); }'
)
"""Small inline auto-update toggle for individual package rows."""

PLUGIN_ROW_UPDATE_STYLE = (
    'QPushButton { padding: 1px 4px; border: 1px solid palette(mid); border-radius: 2px;'
    '  font-size: 10px; min-width: 52px; max-width: 52px; }'
    'QPushButton:disabled { color: palette(mid); border-color: palette(mid); background: transparent; }'
)
"""Small inline update button for individual package rows."""

PLUGIN_ROW_REMOVE_STYLE = (
    'QPushButton { border: none; font-size: 12px; color: #808080;'
    '  padding: 0px 2px; min-width: 18px; max-width: 18px; }'
    'QPushButton:hover { color: #f48771; }'
    'QPushButton:pressed { color: #d4d4d4; }'
    'QPushButton:disabled { color: palette(mid); }'
)
"""Small inline remove (×) button for individual package rows."""

PLUGIN_ROW_ERROR_STYLE = 'font-size: 11px; color: #f48771;'
"""Transient inline error label shown on a row after a failed action."""

PLUGIN_ROW_STATUS_STYLE = 'font-size: 10px; color: #808080;'
"""Muted inline status text shown after an auto-update check (e.g. 'Up to date')."""

PLUGIN_ROW_STATUS_UP_TO_DATE_STYLE = 'font-size: 10px; color: #89d185;'
"""Green status text for 'Up to date'."""

PLUGIN_ROW_STATUS_AVAILABLE_STYLE = 'font-size: 10px; color: #cca700;'
"""Amber status text for 'vX.Y available'."""

PLUGIN_ROW_TIMESTAMP_STYLE = 'font-size: 10px; color: #666666;'
"""Muted relative timestamp label (e.g. '5m ago')."""

PLUGIN_ROW_PROJECT_TAG_STYLE = (
    'QLabel { font-size: 10px; color: #aaaaaa; background: #333333;  border-radius: 8px; padding: 1px 6px; }'
)
"""Compact pill-shaped project name tag for inline dependency display."""

PLUGIN_ROW_PROJECT_TAG_TRANSITIVE_STYLE = (
    'QLabel { font-size: 10px; color: #808080; background: #2a2a2a;'
    '  border-radius: 8px; padding: 1px 6px; font-style: italic; }'
)
"""Dimmed italic project tag for transitive (non-manifest) dependencies."""

# Fixed column widths for visual alignment across rows
PLUGIN_ROW_AUTO_WIDTH = 36
"""Fixed width for the inline Auto toggle button."""

PLUGIN_ROW_UPDATE_WIDTH = 52
"""Fixed width for the inline Update button."""

PLUGIN_ROW_VERSION_MIN_WIDTH = 60
"""Minimum width for the version label column."""

PLUGIN_ROW_STATUS_MIN_WIDTH = 90
"""Minimum width for the inline auto-update status label."""

PLUGIN_ROW_TIMESTAMP_MIN_WIDTH = 40
"""Minimum width for the relative timestamp label."""

PLUGIN_ROW_SPACING = 1
"""Pixels between individual tool/package rows."""

# Project child row — indented sub-row for project-scoped package instances
PROJECT_CHILD_ROW_STYLE = (
    'QFrame#projectChildRow {'
    '  background: transparent;'
    '  border-radius: 4px;'
    '  padding: 2px 8px 2px 40px;'
    '}'
    'QFrame#projectChildRow:hover {'
    '  background: #252628;'
    '}'
)
"""Indented row showing a project-scoped instance of a package."""

PROJECT_CHILD_NAME_STYLE = 'font-size: 11px; color: #999999;'
"""Dimmed package name for project child rows."""

PROJECT_CHILD_PROJECT_STYLE = 'font-size: 11px; color: #808080;'
"""Project label for project child rows."""

PROJECT_CHILD_VERSION_STYLE = 'font-size: 10px; color: #707070;'
"""Version text for project child rows."""

PROJECT_CHILD_TRANSITIVE_STYLE = 'font-size: 10px; color: #666666; font-style: italic;'
"""Dimmed italic label for transitive (non-manifest) dependencies."""

PROJECT_CHILD_NAV_STYLE = (
    'QPushButton { border: none; font-size: 11px; color: #808080;'
    '  padding: 0px 2px; min-width: 18px; max-width: 18px; }'
    'QPushButton:hover { color: #3794ff; }'
    'QPushButton:pressed { color: #d4d4d4; }'
)
"""Navigate arrow button that switches to the Projects tab."""

# Search & filter — toolbar search input and plugin filter chips
SEARCH_INPUT_STYLE = (
    'QLineEdit {'
    '  background: #1e1e1e;'
    '  border: 1px solid palette(mid);'
    '  border-radius: 3px;'
    '  color: #cccccc;'
    '  font-size: 12px;'
    '  padding: 2px 6px;'
    '  min-width: 200px;'
    '  max-width: 300px;'
    '}'
    'QLineEdit:focus { border-color: #3794ff; }'
)
"""Dark search input for the ToolsView toolbar."""

FILTER_CHIP_STYLE = (
    'QPushButton {'
    '  border: 1px solid palette(mid);'
    '  border-radius: 10px;'
    '  padding: 1px 8px;'
    '  font-size: 10px;'
    '  color: #808080;'
    '  background: transparent;'
    '}'
    'QPushButton:checked {'
    '  background: #094771;'
    '  border-color: #3794ff;'
    '  color: #cccccc;'
    '}'
    'QPushButton:hover { color: #cccccc; }'
)
"""Toggleable pill chip for plugin filter in the ToolsView toolbar."""

FILTER_CHIP_SPACING = 4
"""Pixels between filter chips."""

FILTER_PANEL_ANIMATION_MS = 200
"""Duration of the filter panel slide-in / slide-out animation (ms)."""

FILTER_TOGGLE_STYLE = (
    'QPushButton { border: none; font-size: 16px; padding: 2px 6px; }'
    'QPushButton:hover { background: palette(midlight); border-radius: 3px; }'
)
"""Default style for the filter toggle button in the ToolsView toolbar."""

FILTER_TOGGLE_ACTIVE_STYLE = (
    'QPushButton { border: none; font-size: 16px; padding: 2px 6px;'
    '  border-bottom: 2px solid #3794ff; }'
    'QPushButton:hover { background: palette(midlight); border-radius: 3px; }'
)
"""Filter toggle button style when an active filter is in effect."""

# Retained from previous design — auto-update & per-plugin update buttons
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

PLUGIN_SECTION_SPACING = 2
"""Pixels between provider groups in the scroll area."""

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

ACTION_CARD_UPDATE_AVAILABLE_STYLE = (
    'QFrame#actionCard {'
    '  border: 1px solid palette(mid);'
    '  border-radius: 4px;'
    '  background: palette(window);'
    '  padding: 6px 8px;'
    '  opacity: 0.6;'
    '}'
)
"""Faded style for an action card with an available update (managed in Tools)."""

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

ACTION_CARD_STATUS_SATISFIED = 'color: #6a9955; font-size: 11px;'
"""Status label: Already installed (muted green with checkmark)."""

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

ACTION_CARD_STATUS_PENDING = 'color: grey; font-size: 11px; font-style: italic;'
"""Status label: Pending (bare commands with no dry-run check)."""

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

# ---------------------------------------------------------------------------
# Settings window
# ---------------------------------------------------------------------------
SETTINGS_WINDOW_MIN_SIZE = (500, 450)
"""Minimum size (width, height) for the Settings window."""

SETTINGS_GEAR_STYLE = (
    'QPushButton { border: none; font-size: 16px; padding: 2px 6px; }'
    'QPushButton:hover { background: palette(midlight); border-radius: 3px; }'
)
"""Gear button style for the MainWindow tab corner widget."""

# ---------------------------------------------------------------------------
# Settings inline update-status colours
# ---------------------------------------------------------------------------
UPDATE_STATUS_UP_TO_DATE_STYLE = 'color: #89d185; font-size: 12px;'
"""Green text for 'Up to date' / 'Ready' status."""

UPDATE_STATUS_AVAILABLE_STYLE = 'color: #cca700; font-size: 12px;'
"""Orange text for 'Update available' status."""

UPDATE_STATUS_ERROR_STYLE = 'color: #f48771; font-size: 12px;'
"""Red text for error / check-failed status."""

UPDATE_STATUS_CHECKING_STYLE = 'color: #808080; font-size: 12px; font-style: italic;'
"""Grey italic text for 'Checking…' status."""

# ---------------------------------------------------------------------------
# Update banner (in-app self-update notification)
# ---------------------------------------------------------------------------
UPDATE_BANNER_ANIMATION_MS = 250
"""Duration of the slide-in / slide-out animation (ms)."""

UPDATE_BANNER_ERROR_DISMISS_MS = 10000
"""Auto-dismiss delay for the error banner (ms)."""

UPDATE_BANNER_STYLE = (
    'QFrame#updateBanner {  background: #1e3a5f;  border-bottom: 1px solid #2a5a8f;  padding: 6px 12px;}'
)
"""Default banner style — subtle blue tint for downloading state."""

UPDATE_BANNER_READY_STYLE = (
    'QFrame#updateBanner {  background: #1e3f2e;  border-bottom: 1px solid #2a6f3f;  padding: 6px 12px;}'
)
"""Green-tinted banner for "ready to restart" state."""

UPDATE_BANNER_ERROR_STYLE = (
    'QFrame#updateBanner {  background: #3f1e1e;  border-bottom: 1px solid #6f2a2a;  padding: 6px 12px;}'
)
"""Red-tinted banner for error state."""

UPDATE_BANNER_MESSAGE_STYLE = 'color: #d4d4d4; font-size: 12px;'
"""Style for the banner message text."""

UPDATE_BANNER_VERSION_STYLE = 'color: #d4d4d4; font-size: 12px; font-weight: bold;'
"""Style for the version number in the banner."""

UPDATE_BANNER_BTN_STYLE = (
    'QPushButton {'
    '  background: #0e639c;'
    '  color: white;'
    '  border: none;'
    '  border-radius: 3px;'
    '  padding: 4px 12px;'
    '  font-size: 11px;'
    '  font-weight: bold;'
    '}'
    'QPushButton:hover { background: #1177bb; }'
    'QPushButton:pressed { background: #0d5689; }'
)
"""Primary action button style (Restart Now, Retry)."""

UPDATE_BANNER_DISMISS_STYLE = (
    'QPushButton {'
    '  color: #808080;'
    '  border: none;'
    '  font-size: 14px;'
    '  padding: 2px 6px;'
    '}'
    'QPushButton:hover { color: #d4d4d4; }'
)
"""Dismiss (×) button style."""

UPDATE_BANNER_PROGRESS_STYLE = (
    'QProgressBar {'
    '  background: #2a2d2e;'
    '  border: none;'
    '  border-radius: 2px;'
    '  max-height: 3px;'
    '}'
    'QProgressBar::chunk {'
    '  background: #0e639c;'
    '  border-radius: 2px;'
    '}'
)
"""Thin inline progress bar for the downloading state."""

# ---------------------------------------------------------------------------
# Manifest sidebar
# ---------------------------------------------------------------------------
SIDEBAR_WIDTH = 220
"""Fixed width for the manifest sidebar panel."""

SIDEBAR_ITEM_HEIGHT = 32
"""Fixed height for each manifest item row."""

SIDEBAR_SPACING = 2
"""Vertical spacing between manifest items."""

SIDEBAR_STYLE = 'QFrame#sidebar {  background: #252526;  border-right: 1px solid palette(mid);}'
"""Container style for the sidebar panel."""

SIDEBAR_ITEM_STYLE = (
    'QFrame#sidebarItem {'
    '  background: transparent;'
    '  border-radius: 4px;'
    '  padding: 2px 8px;'
    '}'
    'QFrame#sidebarItem:hover {'
    '  background: #2a2d2e;'
    '}'
)
"""Default style for a manifest sidebar item."""

SIDEBAR_ITEM_SELECTED_STYLE = 'QFrame#sidebarItem {  background: #094771;  border-radius: 4px;  padding: 2px 8px;}'
"""Selected manifest sidebar item style — blue highlight."""

SIDEBAR_ITEM_DIMMED_STYLE = (
    'QFrame#sidebarItem {'
    '  background: transparent;'
    '  border-radius: 4px;'
    '  padding: 2px 8px;'
    '  border: 1px dashed palette(mid);'
    '}'
)
"""Dimmed sidebar item for directories whose path or manifest is missing."""

SIDEBAR_LABEL_STYLE = 'font-size: 12px; color: #cccccc;'
"""Sidebar item text label style."""

SIDEBAR_LABEL_DIMMED_STYLE = 'font-size: 12px; color: grey;'
"""Sidebar item text label for dimmed/invalid entries."""

SIDEBAR_CLOSE_STYLE = (
    'QPushButton {'
    '  border: none;'
    '  font-size: 12px;'
    '  color: transparent;'
    '  padding: 0px 2px;'
    '  min-width: 18px;'
    '  max-width: 18px;'
    '}'
    'QFrame#sidebarItem:hover QPushButton { color: #808080; }'
    'QPushButton:hover { color: #d4d4d4 !important; }'
)
"""Close (×) button — hidden until parent row is hovered."""

SIDEBAR_ADD_STYLE = (
    'QPushButton {'
    '  background: transparent;'
    '  border: 1px dashed palette(mid);'
    '  border-radius: 4px;'
    '  font-size: 16px;'
    '  color: #808080;'
    '  padding: 4px;'
    '}'
    'QPushButton:hover { color: #d4d4d4; border-color: #3794ff; }'
)
"""Add (+) button styled at the bottom of the sidebar."""

SIDEBAR_HEADER_STYLE = 'font-size: 11px; font-weight: bold; color: #808080; text-transform: uppercase;'
"""Style for the sidebar section heading."""

SIDEBAR_PHASE_LOADING_STYLE = 'font-size: 10px; color: #3794ff;'
"""Sidebar phase indicator — loading."""

SIDEBAR_PHASE_READY_STYLE = 'font-size: 10px; color: #89d185;'
"""Sidebar phase indicator — ready."""

SIDEBAR_PHASE_ERROR_STYLE = 'font-size: 10px; color: #f48771;'
"""Sidebar phase indicator — error."""

SIDEBAR_PHASE_INSTALLING_STYLE = 'font-size: 10px; color: #d7ba7d;'
"""Sidebar phase indicator — installing."""

SIDEBAR_PHASE_DONE_STYLE = 'font-size: 10px; color: #89d185;'
"""Sidebar phase indicator — done."""

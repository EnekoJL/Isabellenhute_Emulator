"""CustomTkinter-inspired dark theme (QSS) and shared colours for AMS Emulators.

Matches the visual style and design language of NMEA_GPS_simulator_uart and SEVCON_CAN_emulator:
- Deep dark slate/charcoal backgrounds (#1a1a1a / #242424 / #2b2b2b)
- CustomTkinter blue accents (#1f6aa5 / #144870)
- Emerald green start buttons (#10b981 / #059669)
- Amber pause/warning buttons (#f59e0b / #d97706)
- Danger red stop buttons (#ef4444 / #dc2626)
- Modern rounded card containers, clean input widgets and monospace telemetry readouts.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from isascale.presentation.view_models import Tone

# Color Palette — CustomTkinter Dark Blue System
BACKGROUND = "#1a1a1a"
PANEL = "#242424"
CARD = "#2b2b2b"
CARD_HOVER = "#323232"
INPUT_BG = "#343638"
INPUT_BORDER = "#565b5e"
INPUT_FOCUS = "#1f6aa5"
BORDER = "#383838"
BORDER_LIGHT = "#474747"

TEXT = "#f8fafc"
TEXT_DIM = "#94a3b8"
TEXT_MUTED = "#64748b"

ACCENT = "#38bdf8"        # Cyan highlight
PRIMARY_BLUE = "#1f6aa5"  # CustomTkinter Blue
PRIMARY_HOVER = "#144870"
OK = "#10b981"            # Emerald Green
OK_HOVER = "#059669"
WARNING = "#f59e0b"       # Amber
WARNING_HOVER = "#d97706"
ERROR = "#ef4444"         # Danger Red
ERROR_HOVER = "#dc2626"
NEUTRAL = "#6b7280"       # Gray
NEUTRAL_HOVER = "#4b5563"
DARK_BTN = "#334155"      # Utility Slate
DARK_BTN_HOVER = "#475569"

MONO_FONT = "'Consolas', 'JetBrains Mono', 'DejaVu Sans Mono', monospace"
SANS_FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {BACKGROUND};
    color: {TEXT};
    font-family: {SANS_FONT};
    font-size: 10pt;
}}

/* Scroll Areas */
QScrollArea {{
    background-color: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background-color: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: #475569;
    min-height: 24px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background: #64748b;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0px;
}}
QScrollBar::handle:horizontal {{
    background: #475569;
    min-width: 24px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #64748b;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* Card Frames & GroupBoxes */
QGroupBox {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 18px;
    padding: 10px 8px 8px 8px;
    font-weight: bold;
    font-size: 10pt;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: 2px;
    padding: 2px 8px;
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {ACCENT};
    font-size: 9pt;
    font-weight: bold;
    text-transform: uppercase;
}}
QGroupBox QWidget {{
    background-color: transparent;
}}

/* Labels & Typography */
QLabel {{
    color: {TEXT};
    background: transparent;
}}
QLabel[role="dim"] {{
    color: {TEXT_DIM};
    font-size: 9pt;
}}
QLabel[role="muted"] {{
    color: {TEXT_MUTED};
    font-size: 8.5pt;
}}
QLabel[role="header"] {{
    color: {ACCENT};
    font-size: 10pt;
    font-weight: bold;
}}
QLabel[role="value"] {{
    font-family: {MONO_FONT};
    font-size: 14pt;
    font-weight: bold;
    color: {TEXT};
}}
QLabel[role="big"] {{
    font-family: {MONO_FONT};
    font-size: 26pt;
    font-weight: bold;
    color: {ACCENT};
}}

/* Input Controls */
QLineEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {INPUT_BG};
    color: {TEXT};
    border: 1px solid {INPUT_BORDER};
    border-radius: 5px;
    padding: 4px 7px;
    font-family: {MONO_FONT};
    font-size: 9.5pt;
    selection-background-color: {PRIMARY_BLUE};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {ACCENT};
    background-color: #383a3d;
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {TEXT_MUTED};
    background-color: {PANEL};
    border-color: {BORDER};
}}

/* ComboBox / Dropdowns */
QComboBox {{
    background-color: {PRIMARY_BLUE};
    color: #ffffff;
    border: none;
    border-radius: 5px;
    padding: 5px 24px 5px 12px;
    font-weight: bold;
    font-size: 9.5pt;
}}
QComboBox:hover {{
    background-color: {PRIMARY_HOVER};
}}
QComboBox:disabled {{
    background-color: {PANEL};
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 22px;
    border: none;
}}
QComboBox::down-arrow {{
    image: none;
    width: 0px;
    height: 0px;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #ffffff;
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {CARD};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    selection-background-color: {PRIMARY_BLUE};
    selection-color: #ffffff;
    padding: 4px;
    outline: none;
}}

/* PushButtons (Matching CustomTkinter buttons) */
QPushButton {{
    background-color: {DARK_BTN};
    color: {TEXT};
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: bold;
    font-size: 9.5pt;
}}
QPushButton:hover {{
    background-color: {DARK_BTN_HOVER};
}}
QPushButton:pressed {{
    background-color: #1e293b;
}}
QPushButton:disabled {{
    background-color: #1f2227;
    color: {TEXT_MUTED};
}}

QPushButton[role="primary"] {{
    background-color: {OK};
    color: #ffffff;
}}
QPushButton[role="primary"]:hover {{
    background-color: {OK_HOVER};
}}
QPushButton[role="primary"]:pressed {{
    background-color: #047857;
}}

QPushButton[role="blue"] {{
    background-color: {PRIMARY_BLUE};
    color: #ffffff;
}}
QPushButton[role="blue"]:hover {{
    background-color: {PRIMARY_HOVER};
}}

QPushButton[role="warning"] {{
    background-color: {WARNING};
    color: #ffffff;
}}
QPushButton[role="warning"]:hover {{
    background-color: {WARNING_HOVER};
}}

QPushButton[role="danger"] {{
    background-color: {ERROR};
    color: #ffffff;
}}
QPushButton[role="danger"]:hover {{
    background-color: {ERROR_HOVER};
}}
QPushButton[role="danger"]:pressed {{
    background-color: #b91c1c;
}}

QPushButton[role="neutral"] {{
    background-color: {NEUTRAL};
    color: #ffffff;
}}
QPushButton[role="neutral"]:hover {{
    background-color: {NEUTRAL_HOVER};
}}

/* CheckBoxes */
QCheckBox {{
    color: {TEXT};
    spacing: 7px;
    font-size: 9pt;
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {INPUT_BORDER};
    border-radius: 4px;
    background-color: {INPUT_BG};
}}
QCheckBox::indicator:hover {{
    border-color: {ACCENT};
}}
QCheckBox::indicator:checked {{
    background-color: {OK};
    border-color: {OK};
}}

/* Sliders */
QSlider::groove:horizontal {{
    height: 6px;
    background-color: {INPUT_BG};
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    background-color: {PRIMARY_BLUE};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background-color: {ACCENT};
    border: 2px solid #ffffff;
    width: 15px;
    height: 15px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{
    background-color: #ffffff;
}}
QSlider::handle:horizontal:disabled {{
    background-color: {NEUTRAL};
    border-color: {BORDER};
}}

/* Tab Widget (CustomTkinter TabView look) */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    background-color: {PANEL};
    top: -1px;
    padding: 6px;
}}
QTabBar::tab {{
    background-color: {CARD};
    color: {TEXT_DIM};
    border: 1px solid {BORDER};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 7px 16px;
    margin-right: 4px;
    font-weight: bold;
    font-size: 9.5pt;
}}
QTabBar::tab:selected {{
    background-color: {PRIMARY_BLUE};
    color: #ffffff;
    border-color: {PRIMARY_BLUE};
}}
QTabBar::tab:hover:!selected {{
    background-color: {DARK_BTN};
    color: {TEXT};
}}

/* Status Bar */
QStatusBar {{
    background-color: #141414;
    color: {TEXT_DIM};
    border-top: 1px solid {BORDER};
    padding: 3px 8px;
    font-size: 9pt;
}}
"""

TONE_COLORS = {
    Tone.NORMAL: TEXT,
    Tone.DIM: TEXT_DIM,
    Tone.NEUTRAL: NEUTRAL,
    Tone.OK: OK,
    Tone.WARNING: WARNING,
    Tone.ERROR: ERROR,
}


def color(tone: Tone) -> str:
    return TONE_COLORS[tone]


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)

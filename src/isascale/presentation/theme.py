"""Dark industrial/automotive Qt theme (QSS) and shared colours."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from isascale.presentation.view_models import Tone

BACKGROUND = "#121417"
SURFACE = "#1B1E23"
SURFACE_ALT = "#23272E"
BORDER = "#2F343C"
TEXT = "#E6E8EB"
TEXT_DIM = "#8A919C"
ACCENT = "#00B4D8"
OK = "#2ECC71"
WARNING = "#F5A623"
ERROR = "#E74C3C"
NEUTRAL = "#5C636E"

MONO_FONT = "'JetBrains Mono', 'Consolas', 'DejaVu Sans Mono', monospace"

STYLESHEET = f"""
QWidget {{
    background-color: {BACKGROUND};
    color: {TEXT};
    font-size: 10pt;
}}
QGroupBox {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 14px;
    padding: 10px 8px 8px 8px;
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {ACCENT};
    text-transform: uppercase;
}}
QGroupBox QWidget {{ background-color: {SURFACE}; }}
QLabel[role="dim"] {{ color: {TEXT_DIM}; }}
QLabel[role="value"] {{
    font-family: {MONO_FONT};
    font-size: 16pt;
    font-weight: bold;
    color: {TEXT};
}}
QLabel[role="big"] {{
    font-family: {MONO_FONT};
    font-size: 26pt;
    font-weight: bold;
    color: {ACCENT};
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 3px 6px;
    selection-background-color: {ACCENT};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {TEXT_DIM}; }}
QComboBox QAbstractItemView {{ background-color: {SURFACE_ALT}; selection-background-color: {ACCENT}; }}
QPushButton {{
    background-color: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 14px;
    font-weight: bold;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background-color: {ACCENT}; color: {BACKGROUND}; }}
QPushButton:disabled {{ color: {NEUTRAL}; border-color: {SURFACE_ALT}; }}
QPushButton[role="primary"] {{ background-color: {ACCENT}; color: {BACKGROUND}; border: none; }}
QPushButton[role="danger"] {{ background-color: {ERROR}; color: {TEXT}; border: none; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {BORDER}; background: {SURFACE_ALT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; }}
QSlider::groove:horizontal {{ height: 6px; background: {SURFACE_ALT}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {ACCENT}; width: 14px; margin: -5px 0; border-radius: 7px; }}
QStatusBar {{ background-color: {SURFACE}; color: {TEXT_DIM}; border-top: 1px solid {BORDER}; }}
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

"""Shared presentation tokens and Qt styling for the moonlit workspace."""

COLORS = {
    "app": "#101F36", "navigation": "#0D1A2D", "surface": "#142842",
    "inset": "#1A314F", "elevated": "#203A58", "border": "#304864",
    "control": "#6C86A4", "text": "#DCE9FA", "secondary": "#B9CCE2",
    "muted": "#93ACC9", "disabled_text": "#7487A0", "accent": "#8CB9ED",
    "amber": "#E9B86D", "primary": "#315E88", "primary_hover": "#37658F",
    "primary_pressed": "#294F75", "hover": "#203D5E", "pressed": "#294C70",
    "selected": "#25466A", "selected_hover": "#2B5076", "disabled": "#182A41",
    "focus": "#B3D4FF", "success": "#A3D8BA", "success_bg": "#173D35",
    "warning": "#E9B86D", "warning_bg": "#43351F", "error": "#F3A5AF",
    "error_bg": "#452C3B", "error_pressed": "#563244", "info": "#A6CAEF",
    "info_bg": "#1C3857",
}


def apply_theme(app):
    from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
    app.setStyle("Fusion")
    families = QFontDatabase.families()
    family = next((f for f in ("Segoe UI", "Noto Sans") if f in families), app.font().family())
    font = QFont(family)
    font.setPixelSize(14)
    app.setFont(font)
    from . import resource_path
    c = dict(COLORS)
    c["check_icon"] = resource_path("assets/icons/ui/success.svg").as_posix()
    palette = QPalette()
    for role, token in ((QPalette.Window, "app"), (QPalette.WindowText, "text"),
                        (QPalette.Base, "surface"), (QPalette.AlternateBase, "inset"),
                        (QPalette.Text, "text"), (QPalette.Button, "inset"),
                        (QPalette.ButtonText, "text"), (QPalette.Highlight, "selected"),
                        (QPalette.HighlightedText, "text"), (QPalette.ToolTipBase, "elevated"),
                        (QPalette.ToolTipText, "text"), (QPalette.PlaceholderText, "muted")):
        palette.setColor(role, QColor(c[token]))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(c["disabled_text"]))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(c["disabled_text"]))
    app.setPalette(palette)
    # Windows high contrast owns its colors and focus treatment.
    try:
        import ctypes
        from ctypes import wintypes
        class HighContrast(ctypes.Structure):
            _fields_ = [("size", wintypes.UINT), ("flags", wintypes.DWORD), ("scheme", wintypes.LPWSTR)]
        hc = HighContrast()
        hc.size = ctypes.sizeof(hc)
        if ctypes.windll.user32.SystemParametersInfoW(0x0042, hc.size, ctypes.byref(hc), 0) and hc.flags & 1:
            app.setPalette(app.style().standardPalette())
            return
    except (AttributeError, OSError):
        pass
    app.setStyleSheet("""
        QWidget { color: %(text)s; }
        QMainWindow, QStackedWidget { background: %(app)s; }
        QScrollArea > QWidget > QWidget { background: %(surface)s; }
        QWidget[panel="true"] { background: %(surface)s; border: 1px solid %(border)s; border-radius: 12px; }
        QLabel { background: transparent; border: none; }
        QLabel[role="title"] { font-size: 24px; font-weight: 600; }
        QLabel[role="heading"] { font-size: 16px; font-weight: 600; }
        QLabel[role="support"] { color: %(secondary)s; font-size: 13px; }
        QPushButton { background: %(inset)s; border: 1px solid %(control)s; border-radius: 8px;
                      padding: 8px 16px; min-height: 22px; font-weight: 600; }
        QPushButton:hover { background: %(hover)s; }
        QPushButton:pressed { background: %(pressed)s; }
        QPushButton:checked { background: %(selected)s; border-color: %(accent)s; }
        QPushButton:checked:hover { background: %(selected_hover)s; }
        QPushButton[primary="true"] { background: %(primary)s; }
        QPushButton[primary="true"]:hover { background: %(primary_hover)s; }
        QPushButton[primary="true"]:pressed { background: %(primary_pressed)s; }
        QPushButton[destructive="true"] { color: %(error)s; border-color: %(error)s; }
        QPushButton[destructive="true"]:hover { background: %(error_bg)s; }
        QPushButton[destructive="true"]:pressed { background: %(error_pressed)s; }
        QPushButton:flat { background: transparent; border: 2px solid transparent; text-align: left; padding: 6px 8px; font-weight: 400; }
        QPushButton:flat:hover { background: %(hover)s; }
        QPushButton:disabled { background: %(disabled)s; color: %(disabled_text)s; border-color: %(border)s; }
        QPushButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QListWidget:focus { border: 2px solid %(focus)s; }
        QLineEdit, QComboBox, QSpinBox { background: %(inset)s; border: 2px solid %(control)s;
            border-radius: 8px; padding: 8px 12px; min-height: 20px; selection-background-color: %(selected)s; }
        QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: %(disabled_text)s; background: %(disabled)s; }
        QComboBox QAbstractItemView { background: %(elevated)s; selection-background-color: %(selected)s; padding: 8px; }
        QComboBox::drop-down { border: none; width: 24px; }
        QSpinBox::up-button, QSpinBox::down-button { width: 20px; border: none; }
        QCheckBox { spacing: 8px; min-height: 28px; }
        QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid %(control)s; border-radius: 4px; background: %(inset)s; }
        QCheckBox::indicator:checked { background: %(primary)s; border-color: %(accent)s; image: url("%(check_icon)s"); }
        QCheckBox::indicator:hover { border-color: %(focus)s; }
        QCheckBox:focus { outline: 2px solid %(focus)s; }
        QListWidget { background: %(surface)s; border: 1px solid %(border)s; border-radius: 12px; padding: 8px; outline: none; }
        QListWidget::item { border-radius: 8px; padding: 4px; }
        QListWidget::item:hover { background: %(hover)s; }
        QListWidget::item:selected { background: %(selected)s; }
        QScrollArea { border: none; background: transparent; }
        QScrollBar:vertical { width: 12px; background: %(surface)s; margin: 0; }
        QScrollBar:horizontal { height: 12px; background: %(surface)s; margin: 0; }
        QScrollBar::handle { background: %(control)s; border-radius: 6px; min-height: 32px; min-width: 32px; }
        QScrollBar::handle:hover { background: %(muted)s; }
        QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
        QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
        QSplitter::handle { background: %(border)s; }
        QToolTip { background: %(elevated)s; color: %(text)s; border: 1px solid %(control)s; padding: 8px; }
        QDialog, QMessageBox, QInputDialog { background: %(elevated)s; }
        QProgressBar { background: %(border)s; border: none; border-radius: 2px; max-height: 4px; }
        QProgressBar::chunk { background: %(accent)s; }
    """ % c)

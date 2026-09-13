"""Shared high-contrast visual theme for desktop assistant popups."""

from PyQt6 import QtWidgets


BEIGE = "#F3E7CF"
BLACK = "#000000"
BEIGE_HOVER = "#E7D3AE"


def apply_beige_theme(overlay: QtWidgets.QWidget) -> None:
    """Apply the beige/black theme to an already-built popup and its controls."""
    overlay.setStyleSheet(f"QWidget {{ color: {BLACK}; font-weight: bold; }}")
    for widget in overlay.findChildren(QtWidgets.QWidget):
        if isinstance(widget, QtWidgets.QFrame):
            widget.setStyleSheet(
                f"QFrame {{ background-color: {BEIGE}; color: {BLACK}; border: 2px solid {BLACK}; border-radius: 12px; }}"
            )
        elif isinstance(widget, QtWidgets.QPushButton):
            widget.setStyleSheet(
                f"QPushButton {{ background-color: {BEIGE}; color: {BLACK}; border: 2px solid {BLACK}; border-radius: 6px; padding: 5px 10px; font-weight: bold; }}"
                f"QPushButton:hover, QPushButton:checked {{ background-color: {BEIGE_HOVER}; color: {BLACK}; border: 2px solid {BLACK}; }}"
            )
        elif isinstance(widget, (QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit)):
            widget.setStyleSheet(
                f"background-color: {BEIGE}; color: {BLACK}; border: 2px solid {BLACK}; border-radius: 6px; padding: 6px; font-weight: bold;"
            )
        elif isinstance(widget, (QtWidgets.QListWidget, QtWidgets.QTreeWidget, QtWidgets.QTableWidget)):
            widget.setStyleSheet(
                f"background-color: {BEIGE}; color: {BLACK}; border: 2px solid {BLACK}; border-radius: 6px; font-weight: bold;"
            )
        elif isinstance(widget, QtWidgets.QLabel):
            widget.setStyleSheet(f"background: transparent; color: {BLACK}; border: none; font-weight: bold;")
        elif isinstance(widget, QtWidgets.QScrollArea):
            widget.setStyleSheet(f"background: {BEIGE}; color: {BLACK}; border: 2px solid {BLACK};")

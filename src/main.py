"""Main Entry Point for Research Aid Desktop Assistant."""

import logging
import signal
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from PyQt6 import QtCore, QtWidgets

from app import init_application, shutdown_application
from app.models import ShutdownReason
from overlay_ui import get_synonym_overlay_bridge
from overlay_ui.reword_overlay import get_reword_overlay_bridge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
)
log = logging.getLogger("main")


def main():
    print("=" * 65)
    print("[*] Starting Research Aid Desktop Assistant...")
    print("=" * 65)

    # Initialize Qt GUI Application
    qt_app = QtWidgets.QApplication.instance()
    if qt_app is None:
        qt_app = QtWidgets.QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(False)

    # Pre-warm PyQt Sci-Fi Synonym Overlay & Bridge
    bridge = get_synonym_overlay_bridge()
    get_reword_overlay_bridge()

    context = init_application()
    print(f"Session ID  : {context.session_id}")
    print(f"Daemon PID  : {context.daemon_pid}")
    print(f"Health State: {'ONLINE' if context.is_healthy else 'DEGRADED'}")
    print("-" * 65)
    print("Active Global Shortcuts:")
    print("  * Synonyms       : Alt + O (Sci-Fi right-edge popup; Up/Down to navigate, Enter to apply, Esc to cancel)")
    print("  * Definitions    : Ctrl + Shift + D")
    print("  * Table to Graph : Ctrl + Shift + G")
    print("  * Reword         : Alt + P (choose Reword, Add Detail, or Simplify; Enter applies, R regenerates)")
    print("  * Quick Reword   : Ctrl + Shift + R")
    print("  * Discover Papers: Ctrl + Shift + P")
    print("  * Verify Evidence: Ctrl + Shift + E")
    print("  * Source Summary : Ctrl + Shift + U")
    print("=" * 65)
    print("Background listener active. Ready for word processor actions...")
    sys.stdout.flush()

    def handle_signal(sig, frame):
        print("\nShutting down gracefully...")
        shutdown_application(ShutdownReason.USER_QUIT)
        if qt_app:
            qt_app.quit()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Periodic timer to allow Python interpreter to service OS signals (Ctrl+C)
    sig_timer = QtCore.QTimer()
    sig_timer.timeout.connect(lambda: None)
    sig_timer.start(200)

    try:
        qt_app.exec()
    except (KeyboardInterrupt, SystemExit):
        handle_signal(None, None)


if __name__ == "__main__":
    main()

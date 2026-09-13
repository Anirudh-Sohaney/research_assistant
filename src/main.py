"""Main Entry Point for Research Aid Desktop Assistant."""

import logging
import signal
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app import init_application, shutdown_application
from app.models import ShutdownReason

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
)
log = logging.getLogger("main")


def main():
    print("=" * 65)
    print("[*] Starting Research Aid Desktop Assistant...")
    print("=" * 65)

    context = init_application()
    print(f"Session ID  : {context.session_id}")
    print(f"Daemon PID  : {context.daemon_pid}")
    print(f"Health State: {'ONLINE' if context.is_healthy else 'DEGRADED'}")
    print("-" * 65)
    print("Active Global Shortcuts:")
    print("  * Synonyms       : Alt + O (Swap hovered word; press again without moving cursor to cycle 8-12 synonyms)")
    print("  * Definitions    : Ctrl + Shift + D")
    print("  * Table to Graph : Ctrl + Shift + G")
    print("  * Reword Text    : Ctrl + Shift + R")
    print("  * Discover Papers: Ctrl + Shift + P")
    print("  * Verify Evidence: Ctrl + Shift + E")
    print("  * Source Summary : Ctrl + Shift + U")
    print("=" * 65)
    print("Background listener active. Ready for word processor actions...")
    sys.stdout.flush()

    def handle_signal(sig, frame):
        print("\nShutting down gracefully...")
        shutdown_application(ShutdownReason.USER_QUIT)
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        while True:
            time.sleep(1.0)
    except (KeyboardInterrupt, SystemExit):
        handle_signal(None, None)


if __name__ == "__main__":
    main()

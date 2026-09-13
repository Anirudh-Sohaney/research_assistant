"""Convenient shortcut runner for Citation Engine CLI."""

import sys
from pathlib import Path

# Add 'src' to sys.path so citation_engine can be imported directly
src_dir = Path(__file__).resolve().parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from citation_engine.cli import main

if __name__ == "__main__":
    main()

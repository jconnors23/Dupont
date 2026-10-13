"""dupont/__main__.py - Package Executable Entry Point.

==============================================================================
END-TO-END FLOW & PURPOSE:
==============================================================================
Enables running the Dupont chess coaching tool directly as an executable package:
    python -m dupont <path/to/game.pgn>

PEDAGOGICAL EXPLANATION FOR A CS SOPHOMORE:
------------------------------------------
In Python package design, including a `__main__.py` file inside a package directory
turns that directory into an executable module. When a user runs `python -m <pkg_name>`,
Python imports `<pkg_name>` and automatically executes `__main__.py`.

This delegates directly to `dupont.cli.main()`, ensuring the CLI argument parser,
game state machine, Stockfish engine, and Rich terminal REPL initialize properly.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure workspace root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dupont.cli import main

if __name__ == "__main__":
    main()

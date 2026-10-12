#!/usr/bin/env python3
"""run_tests.py - Root Test Runner Entry Point using Pytest.

==============================================================================
END-TO-END FLOW & PURPOSE:
==============================================================================
This module serves as the primary test execution script for the project.
Instead of relying on Python's built-in `unittest` runner, it invokes `pytest`
programmatically to run all unit, mock, and Hypothesis property-based tests.

PEDAGOGICAL EXPLANATION FOR A CS SOPHOMORE:
------------------------------------------
In Python testing, automated runners can be invoked via CLI commands (like `pytest`)
or directly through code via `pytest.main(...)`. Using this script guarantees:
1. Workspace root path (`PROJECT_ROOT`) is always prepended to `sys.path`, preventing
   module resolution errors regardless of the current working directory.
2. CLI agent sessions and CI environments can run `./run_tests.py` or
   `python run_tests.py` as a single safe executable without needing extra flags.
3. Test exit codes (0 for success, non-zero for failures) are propagated cleanly
   to the operating system shell.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure workspace root is in sys.path so tests import project modules reliably
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if __name__ == "__main__":
    # Forward any CLI arguments to pytest (defaulting to tests/ directory if none provided)
    args = sys.argv[1:] if len(sys.argv) > 1 else ["tests"]
    sys.exit(pytest.main(args))

"""core/config.py - Application Configuration and Environment Settings.

==============================================================================
END-TO-END FLOW & PURPOSE:
==============================================================================
This module serves as the centralized configuration manager for the entire
Chess Coaching CLI tool. In software architecture, hardcoding configuration
values (such as binary file paths or API endpoints) directly into business
logic is an anti-pattern. Instead, we adhere to Twelve-Factor App principles by
loading environment variables dynamically from the operating system and from
local `.env` files.

When the application boots:
1. `python-dotenv` loads key-value pairs from any local `.env` file into `os.environ`.
2. The `Config` class queries `os.environ` for custom overrides (e.g., custom Stockfish
   binary paths, alternative LLM base URLs, models, or API keys).
3. If an environment variable is not explicitly defined, fallback defaults are
   computed (such as automatically searching system PATH via `shutil.which` or
   standard Homebrew/Unix installation directories).
4. A singleton instance `config` is instantiated and made available across the
   application, ensuring consistent settings across modules.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

# Step 1: Load environment variables from a local `.env` file if present.
# This prevents leaking sensitive credentials (like API keys) into source control.
load_dotenv()


class Config:
    """Encapsulates application runtime configurations with safe fallback defaults.

    For a sophomore CS student: think of this class as a centralized 'Settings'
    data structure. Instead of scattering `os.getenv(...)` throughout dozens of files,
    we group all settings here. If an environment variable name changes in the future,
    we only have to change it in this one file.
    """

    def __init__(self) -> None:
        # Determine the Stockfish binary path:
        # 1. First, check if 'stockfish' is available anywhere on the user's system PATH
        #    using `shutil.which` (equivalent to running `which stockfish` in bash).
        # 2. If not on PATH, check common default installation locations:
        #    - macOS Homebrew on Apple Silicon: /opt/homebrew/bin/stockfish
        #    - macOS Homebrew on Intel / Linux: /usr/local/bin/stockfish or /usr/bin/stockfish
        default_stockfish = (
            shutil.which("stockfish")
            or "/opt/homebrew/bin/stockfish"
            or "/usr/local/bin/stockfish"
            or "/usr/bin/stockfish"
        )

        # Allow the user to override via environment variable STOCKFISH_PATH
        self.STOCKFISH_PATH: str = os.getenv("STOCKFISH_PATH", default_stockfish)

        # LLM server endpoint. Defaults to a local Ollama instance (OpenAI-compatible /v1 API)
        self.LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")

        # The target LLM model name (e.g., 'llama3.1:8b', 'mistral', 'gpt-4o-mini')
        self.LLM_MODEL: str = os.getenv("LLM_MODEL", "llama3.1:8b")

        # API key for the LLM client. For local Ollama instances, any string works.
        self.OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "ollama")

    def validate_stockfish(self) -> bool:
        """Validates that the configured Stockfish binary path exists and is executable.

        In Unix/POSIX operating systems, a file must not only exist as a regular file,
        it must also have the executable permission bit (X_OK) set to be launched as a
        subprocess.
        """
        path = Path(self.STOCKFISH_PATH)
        return path.is_file() and os.access(path, os.X_OK)


# Singleton instance exported for use across the application.
config = Config()

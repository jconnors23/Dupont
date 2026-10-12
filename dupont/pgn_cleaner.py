#!/usr/bin/env python3
"""dupont/pgn_cleaner.py - PGN Notation Cleaner and Metadata Stripper.

==============================================================================
END-TO-END FLOW & PURPOSE:
==============================================================================
This module provides a standalone CLI script and helper utility to clean PGN
(Portable Game Notation) files before they are parsed or analyzed.

Standard PGN files often contain metadata header tags enclosed in square brackets:
    [Event "Casual Game"]
    [Site "Paris FRA"]
    [Date "1858.10.21"]
    [Round "?"]
    [White "Paul Morphy"]
    [Black "Duke Karl / Count Isouard"]
    [Result "1-0"]

    1. e4 e5 2. Nf3 d6 ...

This cleaner removes all non-chess-notation lines preceding the game moves,
cutting everything above move 1 so the file starts directly with move 1
(e.g., '1. e4 ...' or '1.e4 ...'), and resaves the file in-place.

PEDAGOGICAL EXPLANATION FOR A CS SOPHOMORE:
------------------------------------------
In text processing, domain-specific file formats like PGN are composed of two
grammars: a header grammar (bracketed key-value pairs) and a movetext grammar
(SAN moves, numbers, annotations).

To sanitize the file:
1. We read the source text.
2. We skip bracketed header blocks ('[...]') and empty whitespace lines.
3. We scan for the first token matching the initial move delimiter (e.g. '1.' or '1...').
4. We slice the file text starting from that exact token forward to EOF.
5. We rewrite the file in-place so downstream tools receive pure chess notation.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Union


def clean_pgn_content(content: str) -> str:
    """Strips all metadata and non-chess lines above move 1 from PGN content string.

    Parameters:
        content: Raw PGN file content.

    Returns:
        Cleaned PGN string starting directly with move 1 (e.g. '1. e4 ...').
    """
    lines = content.splitlines()
    start_idx = None
    char_offset = 0

    # Pattern matches '1.' followed by move letter (e.g. '1. e4', '1.e4', '1... e5')
    move_pattern = re.compile(r"\b1\s*\.{1,3}\s*[a-zA-Z]")

    for idx, line in enumerate(lines):
        stripped = line.strip()
        # Skip empty lines and bracketed PGN header tags [Tag "Value"]
        if not stripped or stripped.startswith("["):
            continue

        match = move_pattern.search(line)
        if match:
            start_idx = idx
            char_offset = match.start()
            break
        elif re.match(r"^1\s*\.", stripped):
            start_idx = idx
            char_offset = line.find("1")
            break

    # If no move 1 was found through line inspection, fall back to regex on tag-stripped text
    if start_idx is None:
        tag_stripped = re.sub(r"\[[^\]]*\]", "", content)
        match = move_pattern.search(tag_stripped)
        if match:
            return tag_stripped[match.start():].strip() + "\n"
        return content.strip() + "\n"

    first_line = lines[start_idx][char_offset:]
    cleaned_lines = [first_line] + lines[start_idx + 1:]
    return "\n".join(cleaned_lines).strip() + "\n"


def clean_pgn_file(file_path: Union[str, Path]) -> Path:
    """Cleans a PGN file in-place, removing all lines above move 1 and resaving it.

    Parameters:
        file_path: Path to the PGN file to clean and resave.

    Returns:
        Path object of the cleaned and resaved file.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PGN file not found: {file_path}")

    raw_text = path.read_text(encoding="utf-8")
    cleaned_text = clean_pgn_content(raw_text)

    # Resave the cleaned content back to the file
    path.write_text(cleaned_text, encoding="utf-8")
    return path


def main() -> None:
    """CLI argument entry point for cleaner script."""
    parser = argparse.ArgumentParser(
        description="Clean PGN files by cutting all metadata lines above move 1 and resaving."
    )
    parser.add_argument(
        "targets",
        nargs="+",
        help="One or more PGN file paths or directories to clean.",
    )
    args = parser.parse_args()

    files_cleaned = 0
    for target_str in args.targets:
        target_path = Path(target_str)
        if target_path.is_file():
            clean_pgn_file(target_path)
            print(f"Cleaned and resaved: {target_path}")
            files_cleaned += 1
        elif target_path.is_dir():
            for pgn_file in target_path.glob("**/*.pgn"):
                clean_pgn_file(pgn_file)
                print(f"Cleaned and resaved: {pgn_file}")
                files_cleaned += 1
        else:
            print(f"Warning: Target not found: {target_str}", file=sys.stderr)

    print(f"Completed: Cleaned {files_cleaned} file(s).")


if __name__ == "__main__":
    main()

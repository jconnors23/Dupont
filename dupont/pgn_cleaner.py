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

To sanitize the file or literal text:
1. We read the source text or CLI string argument.
2. We strip any leading 'start' command keyword or prefix.
3. We skip bracketed header blocks ('[...]') and empty whitespace lines.
4. We scan for the first token matching the initial move delimiter (e.g. '1.' or '1...').
5. We slice the file text starting from that exact token forward to EOF.
6. We rewrite the file in-place or print the cleaned movetext for downstream tools.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path
from typing import Union


def clean_pgn_content(content: str) -> str:
    """Strips all metadata, non-chess lines, and 'start' prefixes above move 1 from PGN content.

    Handles standard PGN files, literal pasted games from Chess.com with clocks
    or evaluations, figurines, and inputs prefixed with the 'start' command keyword
    (e.g. 'start [Event ...]' or 'start 1. e4 ...').

    Parameters:
        content: Raw PGN file content or literal pasted PGN string.

    Returns:
        Cleaned PGN string starting directly with move 1 (e.g. '1. e4 ...').
    """
    # Step 1: Strip leading 'start' command prefix if present (case-insensitive)
    # Sophomore CS note: Users often pass CLI commands or copied terminal sessions like
    # 'start [Event "Live Chess"] ...' or 'start 1. e4 ...'. We strip that prefix first
    # so downstream parsers are not confused by non-PGN command keywords.
    normalized = re.sub(r"^\s*start\b\s*:?\s*", "", content, flags=re.IGNORECASE)

    lines = normalized.splitlines()
    start_idx = None
    char_offset = 0

    # Pattern matches '1.' or '1' followed by move letter or figurine:
    # e.g. '1. e4', '1.e4', '1... e5', '1. Nf3', '1. ♘f3', '1 e4', '1. {[%clk ...]} e4'
    move_pattern = re.compile(
        r"\b1\s*(?:\.{1,3}|(?=\s+[a-zA-Z\u2654-\u265F]))\s*(?:\{[^}]*\}\s*)*([a-zA-Z\u2654-\u265F])"
    )

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        match = move_pattern.search(line)
        if match:
            start_idx = idx
            char_offset = match.start()
            break

        # Skip bracketed PGN header tags [Tag "Value"] that do not contain Move 1
        if stripped.startswith("["):
            continue

        if re.match(r"^1\s*[\.:]?\s*[a-zA-Z\u2654-\u265F]", stripped):
            start_idx = idx
            char_offset = line.find("1")
            break

    # If no move 1 was found through line inspection, fall back to regex on tag-stripped text
    if start_idx is None:
        # Only strip standard PGN header tags ([Tag "Value"]), preserving clock/eval comments like {[%clk ...]}
        tag_stripped = re.sub(r"\[[A-Za-z0-9_]+\s+\"[^\"]*\"\]", "", normalized)
        match = move_pattern.search(tag_stripped)
        if match:
            return tag_stripped[match.start():].strip() + "\n"
        # If no moves exist or pattern was not detected, return normalized text stripped of headers
        fallback = tag_stripped.strip()
        return (fallback if fallback else normalized.strip()) + "\n"

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
    """CLI argument entry point for cleaner script.

    Supports:
    - Cleaning files and directories in-place:
        python dupont/pgn_cleaner.py games/1.pgn
    - Cleaning literal pasted PGN strings starting with 'start':
        python dupont/pgn_cleaner.py "start [Event ...] 1. e4 e5"
        python dupont/pgn_cleaner.py start [Event ...] 1. e4 e5
    - Piping raw PGN through stdin:
        cat game.pgn | python dupont/pgn_cleaner.py
    - Writing cleaned output to a specific file:
        python dupont/pgn_cleaner.py "start [Event ...]" -o games/2.pgn
    """
    parser = argparse.ArgumentParser(
        description="Clean PGN files or literal pasted PGN strings by cutting all metadata lines above move 1."
    )
    parser.add_argument(
        "targets",
        nargs="*",
        default=[],
        help="One or more PGN file paths, directories, or literal PGN text to clean.",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output_file",
        help="Optional output file path to write cleaned PGN instead of stdout or in-place file editing.",
    )
    args = parser.parse_args()

    # Case 1: No arguments passed on command line -> check stdin for piped input or clipboard
    if not args.targets:
        if not sys.stdin.isatty():
            raw_input = sys.stdin.read()
            if raw_input.strip():
                cleaned = clean_pgn_content(raw_input)
                if args.output_file:
                    out_path = Path(args.output_file)
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(cleaned, encoding="utf-8")
                    print(f"Cleaned and saved: {out_path}")
                else:
                    sys.stdout.write(cleaned)
                return

        # Check macOS clipboard for copied game
        if sys.platform == "darwin":
            try:
                import subprocess
                res = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=1)
                if res.returncode == 0 and res.stdout.strip():
                    clip = res.stdout.strip()
                    if re.search(r"\b1\s*(?:\.{1,3}|(?=\s+[a-zA-Z\u2654-\u265F]))", clip) or "[Event " in clip:
                        cleaned = clean_pgn_content(clip)
                        if args.output_file:
                            out_path = Path(args.output_file)
                            out_path.parent.mkdir(parents=True, exist_ok=True)
                            out_path.write_text(cleaned, encoding="utf-8")
                            print(f"Cleaned and saved: {out_path}")
                        else:
                            sys.stdout.write(cleaned)
                        return
            except Exception:
                pass

        parser.print_help()
        sys.exit(1)

    # Case 2: Check if all targets are existing filesystem files or directories
    def is_fs_target(t: str) -> bool:
        if "\n" in t or len(t) >= 260:
            return False
        try:
            return Path(t).exists()
        except OSError:
            return False

    all_files_or_dirs = all(is_fs_target(t) for t in args.targets)

    if all_files_or_dirs:
        files_cleaned = 0
        for target_str in args.targets:
            target_path = Path(target_str)
            if target_path.is_file():
                if args.output_file:
                    raw_text = target_path.read_text(encoding="utf-8")
                    cleaned_text = clean_pgn_content(raw_text)
                    out_path = Path(args.output_file)
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(cleaned_text, encoding="utf-8")
                    print(f"Cleaned {target_path} and saved to: {out_path}")
                else:
                    clean_pgn_file(target_path)
                    print(f"Cleaned and resaved: {target_path}")
                files_cleaned += 1
            elif target_path.is_dir():
                for pgn_file in target_path.glob("**/*.pgn"):
                    clean_pgn_file(pgn_file)
                    print(f"Cleaned and resaved: {pgn_file}")
                    files_cleaned += 1
        print(f"Completed: Cleaned {files_cleaned} file(s).")
        return

    # Case 3: Targets represent a literal pasted PGN string (e.g. 'start [Event ...] ...')
    # Sophomore CS note: When a user runs `python pgn_cleaner.py start [Event "Live Chess"] 1. e4 e5`,
    # the shell splits unquoted tokens into multiple items in argv. We join them back together
    # to form the complete pasted PGN string.
    literal_pgn = " ".join(args.targets)
    cleaned = clean_pgn_content(literal_pgn)

    if args.output_file:
        out_path = Path(args.output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(cleaned, encoding="utf-8")
        print(f"Cleaned and saved: {out_path}")
    else:
        sys.stdout.write(cleaned)


if __name__ == "__main__":
    main()


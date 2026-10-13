#!/usr/bin/env python3
"""dupont/cli.py - Interactive Terminal Chess Coaching REPL.

==============================================================================
END-TO-END FLOW & PURPOSE:
==============================================================================
This file is the main executable entry point of the Chess Coaching Tool. It implements
an interactive REPL (Read-Eval-Print Loop) that sits in a terminal split right next to
a student's browser (e.g., analyzing a game played on Chess.com or Lichess).

ARCHITECTURE & END-TO-END WORKFLOW:
1. STARTUP & CLI PARSING:
   - When the user runs `python cli.py <game.pgn>`, `main()` parses the file argument.
   - `ChessCLIApp` loads the game into `GameState`, initializes the `StockfishEngine`
     subprocess, and configures the `ChessCoach` LLM client.
   - Displays the position and the command list as left-aligned tables.
     FEN stays on the position state and is not printed.

2. THE REPL EVENT LOOP (`run()`):
   - KEYBOARD NAVIGATION:
     * 'f' / 'F': Steps forward to the next move immediately.
     * 'b' / 'B': Steps backward to the previous move immediately.
     * Left Arrow key (\\x1b[D or \\x1bOD): Steps backward to the previous move immediately.
     * Right Arrow key (\\x1b[C or \\x1bOC): Steps forward to the next move immediately.
     * 'p' / 'n': Command aliases to step backward/forward.
   - SLASH COMMANDS & ANALYSIS:
     * `/jump 7-w` / `/jump 7-b`: Jumps timeline to that move, updates the board, and displays
       the position summary.
     * `/eval`: Queries Stockfish for top lines and queries Ollama for a short description of
       why each move is suggested at this time in the current game state.
     * `/eval-long`: Sends ONLY the top eval move to Ollama for a lengthy in-depth paragraph
       explanation of why the engine suggests that decision.
     * `eval-score`: Explains why the current White-POV score is even, or why White or Black is ahead.
     * `eval-critical`: Jumps to the next critical decision and explains who is winning and the options.
     * Natural Language Question: Automatically detects if a candidate move or the
       played move is referenced, gathers engine facts, and streams GM coaching advice.
     * `quit`: Breaks loop and triggers deterministic engine shutdown.
   - PRINT: Renders output using rich terminal panels, markdown, and tables.
   - LOOP: Repeats until user exits or sends EOF (Ctrl+D).

3. RESOURCE CLEANUP:
   - Implements a `finally` block ensuring `self.engine.close()` is called, preventing
     orphaned Stockfish subprocesses from running in the background.
"""

from __future__ import annotations

import argparse
import re
import select
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Optional

# Ensure workspace root is in sys.path when invoked directly as a script (e.g. `python dupont/cli.py <pgn>`).
# For a sophomore CS student: When Python runs a file directly with `python path/to/script.py`, Python sets
# sys.path[0] to the script's directory (`dupont/`), NOT the workspace root. To allow absolute package imports
# like `from dupont.coach import ChessCoach` to succeed without requiring `-m` flags or editable installs,
# we dynamically prepend the workspace root directory (one level up) to sys.path before package imports.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import chess
from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from dupont.coach import ChessCoach
from dupont.pgn_cleaner import clean_pgn_content, clean_pgn_file
from dupont.config import config
from dupont.engine import StockfishEngine
from dupont.game_state import GameState

# Console singleton used for all rich terminal I/O
console = Console()


def coach_endpoint() -> tuple[str, int]:
    """Host and port of the configured coach server. Ollama's default is localhost:11434."""
    parsed = urllib.parse.urlparse(config.LLM_BASE_URL)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 11434
    return host, port


def coach_port_open(host: str, port: int) -> bool:
    """True when something is already accepting coach connections."""
    probe = socket.socket()
    probe.settimeout(0.3)
    try:
        probe.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def read_user_action(prompt_text: str = "> ") -> tuple[str, str]:
    """Reads a single user action: Left/Right arrow key navigation or a text command.

    ==========================================================================
    PEDAGOGICAL EXPLANATION FOR A CS SOPHOMORE:
    ==========================================================================
    Standard POSIX terminals operate in 'canonical' (cooked) mode by default.
    In canonical mode, the operating system kernel buffers keystrokes until the
    user presses the Enter key (\\r or \\n). In that mode, arrow keys are consumed
    by the terminal line editor to move the text cursor left and right within
    the input line.

    To detect immediate arrow-key navigation (like pressing Left Arrow to go to
    the previous move or Right Arrow to go to the next move without pressing Enter):
    1. We place the terminal in 'cbreak' mode using `tty.setcbreak(sys.stdin.fileno())`.
       In cbreak mode, characters are available to the program immediately as they are typed.
    2. Terminal arrow keys generate 3-byte ANSI escape sequences:
       - Left Arrow:  '\\x1b[D' or '\\x1bOD'
       - Right Arrow: '\\x1b[C' or '\\x1bOC'
       - Up Arrow:    '\\x1b[A' or '\\x1bOA'
       - Down Arrow:  '\\x1b[B' or '\\x1bOB'
    3. If the input buffer is empty and an arrow sequence arrives, we immediately
       return ('LEFT', '') or ('RIGHT', '') to step through moves instantly!
    4. If the user starts typing letters (like '/eval', '/m 7-w', or asking a question),
       we echo the characters, support Backspace editing, and return ('COMMAND', text)
       when they press Enter.
    5. In non-interactive environments (CI, pipes, automated unit tests), `isatty()`
       is False; we fall back gracefully to standard `sys.stdin.readline()`.
    6. We wrap terminal mode changes in `try ... finally` to ensure the terminal is
       always restored to its original state even on interruption or exception.
    """
    if not sys.stdin.isatty():
        # Non-interactive / piped input fallback (e.g. tests or automated scripts)
        line = sys.stdin.readline()
        if not line:
            return ("QUIT", "")
        trimmed = line.strip()
        if trimmed in ("\x1b[D", "\x1bOD", "left", "LEFT", "/p", "/prev", "p", "prev", "b", "B", "back", "backward", "/b"):
            return ("LEFT", "")
        if trimmed in ("\x1b[C", "\x1bOC", "right", "RIGHT", "/n", "/next", "n", "next", "f", "F", "forward", "/f"):
            return ("RIGHT", "")
        if trimmed.lower() in ("reset", "/reset", "restart", "/restart"):
            return ("RESET", "")
        if trimmed.lower() == "clear":
            return ("CLEAR", "")
        if trimmed.lower() in ("help", "/help"):
            return ("HELP", "")
        if trimmed.lower() in ("quit", "/quit"):
            return ("QUIT", "")
        return ("COMMAND", trimmed)

    # Interactive TTY on Windows
    if sys.platform == "win32":
        try:
            import msvcrt

            sys.stdout.write(prompt_text)
            sys.stdout.flush()
            buffer: list[str] = []
            while True:
                ch = msvcrt.getch()
                if ch in (b"\x00", b"\xe0"):
                    ch2 = msvcrt.getch()
                    if not buffer:
                        if ch2 == b"K":  # Left arrow
                            print()
                            return ("LEFT", "")
                        elif ch2 == b"M":  # Right arrow
                            print()
                            return ("RIGHT", "")
                        elif ch2 == b"H":  # Up arrow
                            print()
                            return ("LEFT", "")
                        elif ch2 == b"P":  # Down arrow
                            print()
                            return ("RIGHT", "")
                    continue
                # Single-key shortcuts when buffer is empty
                elif ch in (b"f", b"F") and not buffer:
                    print()
                    return ("RIGHT", "")
                elif ch in (b"b", b"B") and not buffer:
                    print()
                    return ("LEFT", "")
                elif ch in (b"n", b"N") and not buffer:
                    print()
                    return ("RIGHT", "")
                elif ch in (b"p", b"P") and not buffer:
                    print()
                    return ("LEFT", "")
                elif ch == b"\x03":  # Ctrl+C
                    print()
                    return ("QUIT", "")
                elif ch in (b"\r", b"\n"):
                    print()
                    return ("COMMAND", "".join(buffer).strip())
                elif ch in (b"\x08", b"\x7f"):  # Backspace
                    if buffer:
                        buffer.pop()
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()
                else:
                    try:
                        char_str = ch.decode("utf-8", errors="ignore")
                        if char_str and char_str.isprintable():
                            buffer.append(char_str)
                            sys.stdout.write(char_str)
                            sys.stdout.flush()
                    except Exception:
                        pass
        except ImportError:
            pass

    # Interactive TTY on macOS / Linux (POSIX)
    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    buffer: list[str] = []

    sys.stdout.write(prompt_text)
    sys.stdout.flush()

    try:
        tty.setcbreak(fd)
        while True:
            char = sys.stdin.read(1)
            if not char:
                return ("QUIT", "")

            # Single-key shortcuts when the line is still empty.
            # Only f/b and n/p. Words such as serve, help, quit, and reset
            # are typed in full and submitted with Enter.
            if not buffer:
                if char in ("f", "F"):
                    print()
                    return ("RIGHT", "")
                elif char in ("b", "B"):
                    print()
                    return ("LEFT", "")
                elif char in ("n", "N"):
                    print()
                    return ("RIGHT", "")
                elif char in ("p", "P"):
                    print()
                    return ("LEFT", "")

            # Check for escape sequence (arrow keys, etc.)
            if char == "\x1b":
                # Non-blocking peek for trailing escape sequence bytes
                r, _, _ = select.select([sys.stdin], [], [], 0.05)
                if r:
                    c2 = sys.stdin.read(1)
                    if c2 in ("[", "O"):
                        r2, _, _ = select.select([sys.stdin], [], [], 0.05)
                        if r2:
                            c3 = sys.stdin.read(1)
                            seq = "\x1b" + c2 + c3
                            if seq in ("\x1b[D", "\x1bOD"):  # Left arrow
                                if not buffer:
                                    print()
                                    return ("LEFT", "")
                            elif seq in ("\x1b[C", "\x1bOC"):  # Right arrow
                                if not buffer:
                                    print()
                                    return ("RIGHT", "")
                            elif seq in ("\x1b[A", "\x1bOA"):  # Up arrow -> prev
                                if not buffer:
                                    print()
                                    return ("LEFT", "")
                            elif seq in ("\x1b[B", "\x1bOB"):  # Down arrow -> next
                                if not buffer:
                                    print()
                                    return ("RIGHT", "")
                continue

            elif char in ("\x03", "\x04"):  # Ctrl+C or Ctrl+D
                print()
                return ("QUIT", "")

            elif char in ("\r", "\n"):  # Enter
                print()
                return ("COMMAND", "".join(buffer).strip())

            elif char in ("\x7f", "\x08"):  # Backspace
                if buffer:
                    buffer.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()

            elif ord(char) >= 32:  # Printable character
                buffer.append(char)
                sys.stdout.write(char)
                sys.stdout.flush()

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def render_board(board: chess.Board, last_move: Optional[chess.Move] = None) -> Table:
    """Renders a styled 2D ASCII/Unicode chessboard using rich Table.

    For a sophomore CS student:
    A chessboard is an 8x8 2D grid. In computer chess, ranks run from 1 to 8 (rows)
    and files run from 'a' to 'h' (columns).
    We iterate over ranks in descending order (7 down to 0) so that rank 8 appears at the top,
    matching standard over-the-board perspective.
    """
    table = Table(
        show_header=True,
        header_style="bold cyan",
        box=box.ROUNDED,
        padding=(0, 1),
        title=f"[bold]Board View[/bold] ({'White' if board.turn == chess.WHITE else 'Black'} to move)",
        title_justify="left",
    )
    table.add_column("Rank", justify="left", style="dim")
    for file_char in "a b c d e f g h".split():
        table.add_column(file_char, justify="left")

    # Unicode glyphs for White and Black pieces
    piece_symbols = {
        chess.PAWN: ("♙", "♟"),
        chess.KNIGHT: ("♘", "♞"),
        chess.BISHOP: ("♗", "♝"),
        chess.ROOK: ("♖", "♜"),
        chess.QUEEN: ("♕", "♛"),
        chess.KING: ("♔", "♚"),
    }

    last_from = last_move.from_square if last_move else None
    last_to = last_move.to_square if last_move else None

    # Render ranks 8 down to 1
    for rank in range(7, -1, -1):
        row_cells = [str(rank + 1)]
        for file in range(8):
            sq = chess.square(file, rank)
            piece = board.piece_at(sq)

            # Alternate background colors for dark/light squares
            cell_bg = "on #3a3a3a" if (rank + file) % 2 == 1 else "on #242424"

            # Highlight squares involved in the most recently played move
            if sq in (last_from, last_to):
                cell_bg = "on #5c4d1f"

            if piece is None:
                row_cells.append(f"[{cell_bg}] · [/{cell_bg}]")
            else:
                is_white = piece.color == chess.WHITE
                symbol = piece_symbols[piece.piece_type][0 if is_white else 1]
                color_style = "bold white" if is_white else "bold bright_yellow"
                row_cells.append(f"[{cell_bg}][{color_style}]{symbol}[/{color_style}][/{cell_bg}]")
        table.add_row(*row_cells)

    return table


def get_eval_badge(score_str: str) -> Text:
    """Formats an evaluation string with colored terminal badges.

    Color conventions:
    - Green: Advantage (+0.50 or better)
    - Yellow: Balanced / Equal (-0.50 to +0.50)
    - Red: Disadvantage (-0.50 or worse)
    - Forced Mate: Bold dark red/green highlight
    """
    txt = Text(score_str)
    if "#" in score_str:
        if "+" in score_str:
            txt.stylize("bold white on dark_green")
        else:
            txt.stylize("bold white on dark_red")
    else:
        try:
            val = float(score_str)
            if val > 0.5:
                txt.stylize("bold green")
            elif val < -0.5:
                txt.stylize("bold red")
            else:
                txt.stylize("bold yellow")
        except ValueError:
            txt.stylize("white")
    return txt


def classify_eval_score(score_str: str) -> str:
    """Classifies a White-point-of-view score as even, white ahead, or black ahead.

    A pawn score between -0.50 and +0.50 matches the balanced badge. Mate and
    finished-game results follow the side that is winning.
    """
    text = score_str.strip()
    if text in ("1-0", "1–0"):
        return "white ahead"
    if text in ("0-1", "0–1"):
        return "black ahead"
    if text in ("1/2-1/2", "1/2–1/2", "*"):
        return "even"
    if "#" in text:
        return "black ahead" if "-" in text else "white ahead"
    try:
        value = float(text)
    except ValueError:
        return "even"
    if value > 0.5:
        return "white ahead"
    if value < -0.5:
        return "black ahead"
    return "even"


def material_counts(board: chess.Board) -> tuple[int, int]:
    """Returns (white, black) material, counting a queen as 9 and ignoring kings."""
    values = {
        chess.PAWN: 1,
        chess.KNIGHT: 3,
        chess.BISHOP: 3,
        chess.ROOK: 5,
        chess.QUEEN: 9,
    }
    white = 0
    black = 0
    for piece in board.piece_map().values():
        value = values.get(piece.piece_type, 0)
        if piece.color == chess.WHITE:
            white += value
        else:
            black += value
    return white, black


# A full pawn between the best move and the next one means the choice changes the position.
CRITICAL_GAP_CP = 100


def is_critical_decision(lines: list[dict]) -> bool:
    """A decision is critical when one choice is much better than the alternative.

    Mate, or a gap of at least one pawn between the top two engine lines, counts.
    """
    if not lines:
        return False
    if lines[0].get("is_mate"):
        return True
    if len(lines) < 2:
        return False
    if lines[1].get("is_mate"):
        return True
    top_cp = lines[0].get("score_cp_white")
    second_cp = lines[1].get("score_cp_white")
    if top_cp is None or second_cp is None:
        return False
    return abs(top_cp - second_cp) >= CRITICAL_GAP_CP


def exit_cli() -> None:
    """Clears the session, prints the exit line, and stops the process."""
    console.clear()
    console.print("sys.exit(0)")
    sys.exit(0)


def print_section_banner(title: str) -> None:
    """Prints a full-width cyan rule so each block is easy to find."""
    console.print()
    console.rule(
        f"[bold cyan]{title}[/bold cyan]",
        style="cyan",
        align="left",
        characters="═",
    )


_CHESS_TOKEN = re.compile(
    r"(?P<notation>(?<![A-Za-z0-9])(?:"
    r"O-O-O|O-O|0-0-0|0-0|"
    r"[NBRQK][a-h]?[1-8]?x?[a-h][1-8](?:=[NBRQK])?[+#]?|"
    r"[a-h](?:x[a-h])?[1-8](?:=[NBRQK])?[+#]?"
    r")(?![A-Za-z0-9]))"
    r"|(?P<piece>\b(?:pawns?|knights?|bishops?|rooks?|queens?|kings?)\b)"
    r"|(?P<check>\b(?:checkmates?|checks?)\b)"
    r"|(?P<capture>\b(?:capturing|captures|capture)\b)"
    r"|(?P<castle>\b(?:castling|castles|castle|kingside|queenside)\b)"
    r"|(?P<white>\bwhite\b)"
    r"|(?P<black>\bblack\b)"
    r"|(?P<good>\b(?:advantages?|winning|ahead)\b)"
    r"|(?P<bad>\b(?:disadvantages?|losing)\b)"
    r"|(?P<even>\beven\b)"
    r"|(?P<tactic>\b(?:forks?|pins?|skewers?|discovered|sacrifices?)\b)"
    r"|(?P<score>[+-]\d+\.\d+|#[+-]?\d+)"
    r"|(?P<command>\beval-critical\b|\beval-score\b|\beval-long\b|\beval\b)",
    re.IGNORECASE,
)

_CHESS_STYLES = {
    "notation": "bold gold1",
    "piece": "bold green",
    "check": "bold red",
    "capture": "bold yellow",
    "castle": "bold magenta",
    "white": "bold white",
    "black": "bold cyan",
    "good": "bold yellow",
    "bad": "bold red",
    "even": "bold cyan",
    "tactic": "bold magenta",
    "score": "bold cyan",
    "command": "bold cyan",
}


def style_chess_prose(text: str) -> Text:
    """Colors notation gold, piece names green, and the other chess keywords."""
    cleaned = re.sub(r"[*`]", "", text)
    cleaned = re.sub(r"(?m)^>\s?", "", cleaned)
    cleaned = re.sub(r"(?m)^#{1,6}\s*", "", cleaned)
    styled = Text()
    cursor = 0
    for match in _CHESS_TOKEN.finditer(cleaned):
        if match.start() > cursor:
            styled.append(cleaned[cursor:match.start()])
        kind = match.lastgroup or ""
        styled.append(match.group(), style=_CHESS_STYLES.get(kind, ""))
        cursor = match.end()
    if cursor < len(cleaned):
        styled.append(cleaned[cursor:])
    return styled


def _styled_move_header(label: str, move_san: str, score: str, continuation: str) -> Text:
    """Header line with the move in gold and the continuation colored the same way."""
    header = Text()
    header.append(label, style="bold")
    header.append_text(style_chess_prose(move_san))
    header.append(" (Eval: ")
    header.append_text(style_chess_prose(score))
    header.append(")")
    if continuation:
        header.append("\nContinuation: ", style="dim")
        header.append_text(style_chess_prose(continuation))
    return header


def _styled_state_header(score: str, verdict: str, detail: str, continuation: str) -> Text:
    """Score line plus the colored detail under it."""
    header = Text()
    header.append_text(style_chess_prose(score))
    header.append("  ")
    header.append_text(style_chess_prose(verdict))
    if detail:
        header.append("\n")
        header.append_text(style_chess_prose(detail))
    if continuation:
        header.append("\nContinuation: ", style="dim")
        header.append_text(style_chess_prose(continuation))
    return header


def describe_engine_move(san: str) -> str:
    """Turns a SAN move into a short phrase such as 'knight moves to h6'."""
    text = san.strip().lower()
    if text in ("", "none"):
        return "no move"

    suffix = ""
    if text.endswith("#"):
        suffix = ", giving checkmate"
        text = text[:-1]
    elif text.endswith("+"):
        suffix = ", giving check"
        text = text[:-1]

    if text == "o-o":
        return f"king castles kingside{suffix}"
    if text == "o-o-o":
        return f"king castles queenside{suffix}"

    promotion = ""
    if "=" in text:
        text, promo = text.split("=", 1)
        promo_names = {"q": "queen", "r": "rook", "b": "bishop", "n": "knight"}
        promotion = f" and promotes to {promo_names.get(promo, promo)}"

    piece_names = {"n": "knight", "b": "bishop", "r": "rook", "q": "queen", "k": "king"}
    piece = "pawn"
    if text[:1] in piece_names:
        piece = piece_names[text[0]]
        text = text[1:]

    verb = "captures on" if "x" in text else "moves to"
    square = text.replace("x", "")[-2:]
    return f"{piece} {verb} {square}{promotion}{suffix}"


class ChessCLIApp:
    """Coordinates the interactive REPL lifecycle, engine communication, and coaching responses.

    This class serves as the 'Controller' in an MVC-style pattern:
    - Model: GameState and StockfishEngine
    - View: Rich Console, Panels, Tables
    - Controller: REPL dispatch loop in run()
    """

    def __init__(self, pgn_path: str) -> None:
        raw_source = str(pgn_path)
        is_existing_file = False
        if "\n" not in raw_source and len(raw_source) < 260:
            try:
                is_existing_file = Path(raw_source).is_file()
            except OSError:
                is_existing_file = False

        # If source is not an existing file on disk, parse directly as literal pasted PGN in-memory
        # (e.g. 'start [Event ...] 1. e4 e5' or raw movetext) without needing any filesystem directory.
        if not is_existing_file:
            cleaned_text = clean_pgn_content(raw_source)
            if not cleaned_text.strip():
                console.print(f"[bold red]Error:[/bold red] File not found or empty PGN: {pgn_path}")
                sys.exit(1)
            self.pgn_path = None
            try:
                self.game = GameState(cleaned_text)
            except Exception as e:
                console.print(f"[bold red]Failed to load PGN:[/bold red] {e}")
                sys.exit(1)
        else:
            self.pgn_path = Path(raw_source)
            # Step 0: Clean non-chess notation lines from PGN file and resave it starting at move 1
            try:
                clean_pgn_file(self.pgn_path)
            except Exception as e:
                console.print(f"[dim]Note on PGN cleaning: {e}[/dim]")

            # Step 1: Parse and index the PGN game
            try:
                self.game = GameState(self.pgn_path)
            except Exception as e:
                console.print(f"[bold red]Failed to load PGN:[/bold red] {e}")
                sys.exit(1)

        # Initialize timeline pointer to Move 1 (ply 1) if moves exist
        # This displays Move 1 played (e.g. 1. Previous Move (white played e4)) on startup
        if len(self.game.plies) >= 1:
            self.game.current_ply_index = 1
        else:
            self.game.current_ply_index = 0

        # Step 2: Spawn Stockfish engine subprocess
        console.print("[dim]Initializing Stockfish engine...[/dim]")
        try:
            self.engine = StockfishEngine()
        except Exception as e:
            console.print(f"[bold red]Stockfish Initialization Error:[/bold red] {e}")
            sys.exit(1)

        # Step 3: Initialize the conversational coach adapter
        console.print("[dim]Initializing Grandmaster Coach...[/dim]")
        self.coach = ChessCoach()
        # Fullmove number last printed. Stepping onto the next whole move clears the screen.
        self.last_shown_fullmove: Optional[int] = None
        # The opening screen leads with commands. Later views put them under the position.
        self.commands_on_top = True

    def command_rows(self, *, include_help: bool = True) -> list[tuple[str, str]]:
        """Commands in the order a new session needs them. Help is omitted on the help screen."""
        rows = [
            ("serve", "start the coach and wait until it is ready"),
            ("f", "step forward"),
            ("b", "step back"),
            ("eval", "short coach notes on the top moves"),
            ("eval-long", "a longer explanation of the top move"),
            ("eval-score", "why the score is even, or why one side is ahead"),
            ("eval-critical", "jump to the next critical decision and explain it"),
            ("reset", "jump to the start of the game"),
            ("quit", "quit"),
        ]
        if include_help:
            rows.insert(-1, ("help", "show these commands"))
        return rows

    def print_manual(self, *, include_help: bool = True) -> None:
        """Prints the command list as a cyan two-column table under a banner."""
        print_section_banner("commands")
        commands = Table(
            box=box.SQUARE,
            show_header=True,
            show_lines=True,
            header_style="bold cyan",
            border_style="cyan",
            padding=(0, 1),
        )
        commands.add_column("command", justify="left", style="bold cyan", no_wrap=True)
        commands.add_column("action", justify="left")
        for command, action in self.command_rows(include_help=include_help):
            commands.add_row(command, action)
        console.print(commands)

    def print_welcome_banner(self) -> None:
        """Displays the short command list."""
        self.print_manual()

    def get_position_ui_lines(self) -> list[str]:
        """Builds the position summary as plain lines.

        Order:
        1. previous move: <color> played <san>
        2. current move: 5 on White's turn, 5.5 on Black's turn
        3. turn: white to move, or black to move
        4. stockfish: <san>, then a plain-language description and a pointer to eval
        5. score: +0.5

        The FEN stays on the board and on each ply record. It is not printed.
        """
        board = self.game.current_board

        idx = self.game.current_ply_index
        if idx == 0 or not self.game.plies:
            prev_move_str = "previous move: none"
        else:
            prev_ply = self.game.plies[idx - 1]
            color_str = "white" if prev_ply.is_white else "black"
            prev_move_str = f"previous move: {color_str} played {prev_ply.san.lower()}"

        turn_name = "white" if board.turn == chess.WHITE else "black"
        move_number = board.fullmove_number
        move_label = str(move_number) if board.turn == chess.WHITE else f"{move_number}.5"
        current_move_str = f"current move: {move_label}"
        turn_str = f"turn: {turn_name} to move"

        analysis = self.engine.analyze_position(board, depth=14, multipv=1)
        best_move = (analysis.get("best_move") or "none").lower()
        best_score = analysis.get("best_eval", "0.00")
        suggestion_str = (
            f"stockfish: {best_move}\n"
            f"stockfish recommends {describe_engine_move(best_move)}\n"
            "to understand why, do eval"
        )
        eval_score_str = f"score: {best_score}"

        return [prev_move_str, current_move_str, turn_str, suggestion_str, eval_score_str]

    def get_position_ui_text(self) -> str:
        """Returns the position summary as a single string."""
        return "\n".join(self.get_position_ui_lines())

    def show_position_summary(self, *, stepped: bool = False) -> None:
        """Prints the position table. Commands appear only on the opening view.

        Stockfish's notation stays gold. The FEN is not printed. A whole move and
        its half stay on screen together. Stepping from 8.5 to 9 clears first.
        """
        board = self.game.current_board
        fullmove = board.fullmove_number
        if (
            stepped
            and board.turn == chess.WHITE
            and self.last_shown_fullmove is not None
            and fullmove > self.last_shown_fullmove
        ):
            console.clear()
        self.last_shown_fullmove = fullmove

        previous, current, turn, suggestion, score = self.get_position_ui_lines()
        san, recommendation, why = suggestion.split("\n", 2)
        stockfish = Text()
        stockfish.append(san.split(": ", 1)[1], style="bold gold1")
        stockfish.append("\n")
        stockfish.append_text(style_chess_prose(recommendation))
        stockfish.append("\n")
        stockfish.append_text(style_chess_prose(why))

        commands_first = self.commands_on_top
        self.commands_on_top = False
        if commands_first:
            self.print_manual()

        print_section_banner("position")
        position = Table(
            box=box.SQUARE,
            show_header=False,
            show_lines=True,
            border_style="cyan",
            padding=(0, 1),
        )
        position.add_column(justify="left", style="bold cyan", no_wrap=True)
        position.add_column(justify="left")
        position.add_row("previous move", style_chess_prose(previous.split(": ", 1)[1]))
        position.add_row("current move", current.split(": ", 1)[1])
        position.add_row("turn", style_chess_prose(turn.split(": ", 1)[1]))
        position.add_row("stockfish", stockfish)
        position.add_row("score", Text(score.split(": ", 1)[1], style="bold cyan"))
        console.print(position)

    def cmd_serve(self) -> None:
        """Starts `ollama serve` if needed and returns once the coach accepts connections."""
        host, port = coach_endpoint()
        if coach_port_open(host, port):
            console.print(f"coach ready  {host}:{port}")
            return

        ollama = shutil.which("ollama")
        if not ollama:
            console.print("ollama not found")
            return

        # Detach so the server keeps running after this command returns to the prompt.
        subprocess.Popen(
            [ollama, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            if coach_port_open(host, port):
                console.print(f"coach ready  {host}:{port}")
                return
            time.sleep(0.2)
        console.print(f"coach not ready  {host}:{port}")

    def cmd_restart(self) -> None:
        """Jumps to the position before any moves and shows that board."""
        if self.game.plies:
            self.game.jump_to_ply(0)
        else:
            self.game.current_ply_index = 0
        console.clear()
        self.show_position_summary()

    def cmd_jump_move(self, arg: str) -> None:
        """Navigates to a specific move in the game timeline (e.g. '14', '14w', '14b')."""
        try:
            move_num, is_white = GameState.parse_move_specifier(arg)
            self.game.jump_to_move(move_num, is_white)
            self.show_position_summary(stepped=True)
        except Exception as e:
            console.print(f"[bold red]Navigation error:[/bold red] {e}")

    def cmd_eval_short(self) -> None:
        """Executes a Multi-PV search (depth 16) and renders the top candidate moves in a table."""
        board = self.game.current_board
        with console.status("[cyan]Computing top candidate lines with Stockfish (depth 16)...[/cyan]"):
            analysis = self.engine.analyze_position(board, depth=16, multipv=2)

        table = Table(
            title=f"Stockfish Evaluation - Top Candidate Lines ({'White' if board.turn == chess.WHITE else 'Black'} to move)",
            title_justify="left",
            box=box.ROUNDED,
            header_style="bold magenta",
        )
        table.add_column("#", justify="left", style="dim", width=4)
        table.add_column("Move", justify="left", style="bold cyan", width=10)
        table.add_column("Eval (White POV)", justify="left", width=18)
        table.add_column("Continuation Line (PV)", style="white")

        for line in analysis.get("lines", [])[:2]:
            pv_str = " ".join(line.get("pv_san", [])[:7])
            table.add_row(
                str(line["rank"]),
                line["move"],
                get_eval_badge(line["score_display"]),
                pv_str,
            )

        console.print(table)

    def cmd_eval(self) -> None:
        """Outputs each top engine line and a short Ollama explanation of why that move is suggested at this time."""
        board = self.game.current_board
        with console.status("[cyan]Computing top candidate lines with Stockfish (depth 16)...[/cyan]"):
            analysis = self.engine.analyze_position(board, depth=16, multipv=2)

        lines = analysis.get("lines", [])[:2]
        if not lines:
            console.print("[yellow]No candidate lines found in this position.[/yellow]")
            return

        turn_side = "White" if board.turn == chess.WHITE else "Black"
        console.print(f"\n[bold cyan]Top Candidate Moves & Explanations ({turn_side} to move):[/bold cyan]\n")

        for line in lines:
            rank = line["rank"]
            move_san = line["move"]
            score = line["score_display"]
            pv_str = " ".join(line.get("pv_san", [])[:6])

            # Send prompt to Ollama asking why this move is suggested at this time
            with console.status(f"[magenta]Asking Coach why {move_san} is suggested at this time...[/magenta]"):
                facts = {
                    "fen": board.fen(),
                    "turn": turn_side,
                    "candidate_san": move_san,
                    "score_display": score,
                    "continuation": pv_str,
                }
                system_prompt = (
                    "You are a Grandmaster chess coach. When asked why a move is suggested at this time, "
                    "provide a concise description (1-2 sentences) explaining why that move is suggested "
                    "in the current game state based on the provided engine facts."
                )
                prompt = f"Why is {move_san} suggested at this time?"
                explanation = self.coach.chat(prompt, facts, system_prompt=system_prompt)

            console.print(
                Panel(
                    Group(
                        _styled_move_header(f"Line {rank}: ", move_san, score, pv_str),
                        style_chess_prose(explanation.strip()),
                    ),
                    title=f"[bold]Candidate Move {rank}: {move_san}[/bold]",
                    title_align="left",
                    border_style="cyan",
                )
            )

    def cmd_eval_long(self) -> None:
        """Sends ONLY the top eval move to Ollama for a lengthy paragraph explanation of why it is suggested."""
        board = self.game.current_board
        with console.status("[cyan]Computing top candidate move with Stockfish (depth 16)...[/cyan]"):
            analysis = self.engine.analyze_position(board, depth=16, multipv=1)

        lines = analysis.get("lines", [])
        if not lines:
            console.print("[yellow]No candidate lines found in this position.[/yellow]")
            return

        top_line = lines[0]
        move_san = top_line["move"]
        score = top_line["score_display"]
        pv_str = " ".join(top_line.get("pv_san", [])[:7])
        turn_side = "White" if board.turn == chess.WHITE else "Black"

        with console.status(f"[magenta]Generating in-depth coaching analysis for top move {move_san}...[/magenta]"):
            facts = {
                "fen": board.fen(),
                "turn": turn_side,
                "candidate_san": move_san,
                "best_move_san": move_san,
                "score_display": score,
                "continuation": pv_str,
            }
            system_prompt = (
                "You are an expert Grandmaster chess coach. When asked why a move is suggested at this time, "
                "provide a lengthy, comprehensive explanation (at least a full paragraph) "
                "explaining why that decision is being suggested by the evaluation engine in the current game state. "
                "Detail the tactical motifs, positional plans, piece activity, and long-term consequences."
            )
            prompt = f"Why is {move_san} suggested at this time?"
            explanation = self.coach.chat(prompt, facts, system_prompt=system_prompt)

        console.print(
            Panel(
                Group(
                    _styled_move_header("Top Move: ", move_san, score, pv_str),
                    style_chess_prose(explanation.strip()),
                ),
                title=f"[bold green]In-Depth Top Move Analysis: {move_san}[/bold green]",
                title_align="left",
                subtitle="[dim]Comprehensive Evaluation Explanation[/dim]",
                subtitle_align="left",
                border_style="green",
            )
        )

    def cmd_eval_critical(self) -> None:
        """Jumps to the next critical decision and explains who is winning and the options."""
        start = self.game.current_ply_index
        if start >= len(self.game.plies):
            console.print("no critical decision left in this game")
            return

        found: Optional[int] = None
        with console.status("[cyan]Looking for the next critical decision...[/cyan]"):
            for idx in range(start, len(self.game.plies)):
                board = chess.Board(self.game.plies[idx].fen_before)
                analysis = self.engine.analyze_position(board, depth=10, multipv=2)
                if is_critical_decision(analysis.get("lines", [])):
                    found = idx
                    break

        if found is None:
            console.print("no critical decision left in this game")
            return

        self.commands_on_top = False
        self.game.jump_to_ply(found)
        self.show_position_summary()

        board = self.game.current_board
        with console.status("[cyan]Reading the critical position with Stockfish (depth 16)...[/cyan]"):
            analysis = self.engine.analyze_position(board, depth=16, multipv=2)

        lines = analysis.get("lines", [])
        if not lines:
            console.print("[yellow]No candidate lines found in this position.[/yellow]")
            return

        score = str(lines[0].get("score_display", analysis.get("best_eval", "0.00")))
        verdict = classify_eval_score(score)
        verdict_label = {
            "even": "even",
            "white ahead": "white is ahead",
            "black ahead": "black is ahead",
        }[verdict]
        turn_side = "White" if board.turn == chess.WHITE else "Black"
        option_bits = [
            f"{line['move']} ({line['score_display']})"
            for line in lines[:2]
        ]
        options = ", ".join(option_bits)
        pv_str = " ".join(lines[0].get("pv_san", [])[:7])
        played = self.game.current_ply.san if self.game.current_ply else "none"
        white_material, black_material = material_counts(board)

        with console.status("[magenta]Asking Coach about this critical decision...[/magenta]"):
            facts = {
                "fen": board.fen(),
                "turn": turn_side,
                "played_move": played,
                "score_display": score,
                "score_verdict": verdict,
                "best_move_san": lines[0]["move"],
                "best_eval_white": score,
                "continuation": pv_str,
                "options": options,
                "material_white": white_material,
                "material_black": black_material,
            }
            system_prompt = (
                "You are an expert Grandmaster chess coach. The evaluation is from White's point of view. "
                "Write one full paragraph on this critical decision: who is winning and why, then the real "
                "options for the side to move and what each option is trying to do. Use the engine lines. "
                "Do not change the verdict."
            )
            prompt = f"Who is winning at {score}, and what are {turn_side}'s options?"
            explanation = self.coach.chat(prompt, facts, system_prompt=system_prompt)

        console.print(
            Panel(
                Group(
                    _styled_state_header(score, verdict_label, f"{turn_side} to move. Options: {options}", pv_str),
                    style_chess_prose(explanation.strip()),
                ),
                title="[bold]critical decision[/bold]",
                title_align="left",
                border_style="cyan",
            )
        )

    def cmd_eval_score(self) -> None:
        """Explains why the current score is even, or why White or Black is ahead."""
        board = self.game.current_board
        with console.status("[cyan]Reading the evaluation with Stockfish (depth 16)...[/cyan]"):
            analysis = self.engine.analyze_position(board, depth=16, multipv=1)

        score = str(analysis.get("best_eval", "0.00"))
        verdict = classify_eval_score(score)
        verdict_label = {
            "even": "even",
            "white ahead": "white is ahead",
            "black ahead": "black is ahead",
        }[verdict]
        best_move = analysis.get("best_move") or "none"
        pv_str = " ".join(analysis.get("best_pv", [])[:7])
        white_material, black_material = material_counts(board)
        turn_side = "White" if board.turn == chess.WHITE else "Black"

        question = {
            "even": f"Why is this position even at {score}?",
            "white ahead": f"Why is White ahead at {score}?",
            "black ahead": f"Why is Black ahead at {score}?",
        }[verdict]
        with console.status(f"[magenta]Asking Coach why the position is {verdict_label}...[/magenta]"):
            facts = {
                "fen": board.fen(),
                "turn": turn_side,
                "score_display": score,
                "score_verdict": verdict,
                "best_move_san": best_move,
                "best_eval_white": score,
                "continuation": pv_str,
                "material_white": white_material,
                "material_black": black_material,
            }
            system_prompt = (
                "You are a Grandmaster chess coach. The evaluation is from White's point of view: "
                "positive means White is ahead, negative means Black is ahead, and a score from "
                "-0.50 to +0.50 is even. Explain in one short paragraph why the position matches "
                "the given verdict. Use material, pawn structure, king safety, and piece activity. "
                "Do not change the verdict."
            )
            explanation = self.coach.chat(question, facts, system_prompt=system_prompt)

        console.print(
            Panel(
                Group(
                    _styled_state_header(
                        score,
                        verdict_label,
                        f"Material: white {white_material}, black {black_material}",
                        "",
                    ),
                    style_chess_prose(explanation.strip()),
                ),
                title="[bold]eval score[/bold]",
                title_align="left",
                border_style="cyan",
            )
        )

    def cmd_refute(self, candidate_str: str) -> None:
        """Evaluates why a specific candidate move is suboptimal or losing.

        Flow:
        1. Validate legality using GameState.parse_candidate_move.
        2. Calculate refutation line and eval delta using Stockfish.
        3. Print deterministic refutation card.
        4. Pass structured facts to LLM coach to explain the tactical motif.
        """
        board = self.game.current_board
        cand_move = GameState.parse_candidate_move(board, candidate_str)

        if not cand_move:
            console.print(
                f"[bold red]Invalid Move:[/bold red] '{candidate_str}' is not a legal move in this position."
            )
            return

        with console.status(f"[cyan]Stockfish calculating refutation for {candidate_str}...[/cyan]"):
            refutation = self.engine.refute_candidate(board, cand_move, depth=16)

        # Render deterministic engine refutation card
        info_table = Table.grid(padding=(0, 2))
        info_table.add_column(style="bold cyan")
        info_table.add_column()

        info_table.add_row("Candidate Move:", f"{refutation['candidate_san']} ({refutation['candidate_uci']})")
        info_table.add_row("Classification:", f"[bold yellow]{refutation['classification']}[/bold yellow]")
        info_table.add_row("Evaluation Delta:", f"[bold]{refutation['eval_delta_display']}[/bold]")
        info_table.add_row("Stockfish Best Move:", f"{refutation['best_move_san']} (Eval: {refutation['best_eval_white']})")

        if refutation.get("punishing_move_san"):
            opp = refutation.get("opponent_color", "Opponent")
            line = " ".join(refutation.get("punishing_line_san", []))
            info_table.add_row(f"{opp}'s Refutation:", f"[bold red]{refutation['punishing_move_san']}[/bold red]")
            info_table.add_row("Punishing Line:", f"[red]{line}[/red]")

        console.print(
            Panel(
                info_table,
                title="[bold red]Deterministic Engine Refutation[/bold red]",
                title_align="left",
                border_style="red",
            )
        )

        # Trigger conversational coach explanation
        with console.status("[magenta]Coach analyzing tactical motifs...[/magenta]"):
            user_q = f"Why couldn't I play {refutation['candidate_san']} in this position?"
            coach_reply = self.coach.chat(user_q, refutation)

        console.print(Panel(style_chess_prose(coach_reply), title="[bold green]Grandmaster Coach Analysis[/bold green]", title_align="left", border_style="green"))

    def cmd_ask_coach(self, question: str) -> None:
        """Handles conversational questions, automatically grounding them with engine analysis.

        Examples:
        - 'Why is this move a mistake?' -> Analyzes the move played on this ply.
        - 'Why couldn't I play exd5?' -> Detects candidate move 'exd5', computes refutation.
        - 'What was White threatening?' -> Analyzes candidate threats and king safety.
        """
        board = self.game.current_board
        ply = self.game.current_ply

        with console.status("[cyan]Analyzing board context with Stockfish...[/cyan]"):
            analysis = self.engine.analyze_position(board, depth=16, multipv=2)

            # Heuristic: Check if the user mentioned a specific legal candidate move in their query
            mentioned_move: Optional[chess.Move] = None
            for token in re.findall(r"[a-zA-Z0-9#+=?-]+", question):
                parsed = GameState.parse_candidate_move(board, token)
                if parsed:
                    mentioned_move = parsed
                    break

            refutation: Optional[dict[str, Any]] = None
            if mentioned_move:
                refutation = self.engine.refute_candidate(board, mentioned_move, depth=16)
            elif ply and ply.move:
                # If question is about the played move ("Why is this a mistake?")
                refutation = self.engine.refute_candidate(board, ply.move, depth=16)

            engine_facts = {
                "fen": board.fen(),
                "turn": "White" if board.turn == chess.WHITE else "Black",
                "played_move": ply.san if ply else "None",
                "best_move_san": analysis.get("best_move"),
                "best_eval_white": analysis.get("best_eval"),
                "lines": analysis.get("lines", []),
            }

            if refutation:
                engine_facts.update(
                    {
                        "candidate_san": refutation.get("candidate_san"),
                        "mover_color": refutation.get("mover_color"),
                        "opponent_color": refutation.get("opponent_color"),
                        "eval_delta_display": refutation.get("eval_delta_display"),
                        "classification": refutation.get("classification"),
                        "punishing_move_san": refutation.get("punishing_move_san"),
                        "punishing_line_san": refutation.get("punishing_line_san"),
                        "after_eval_white": refutation.get("after_eval_white"),
                    }
                )

        with console.status("[magenta]Coach drafting response...[/magenta]"):
            reply = self.coach.chat(question, engine_facts)

        console.print(Panel(style_chess_prose(reply), title="[bold green]Grandmaster Coach[/bold green]", title_align="left", border_style="green"))

    def print_help(self) -> None:
        """Displays the command table without the help row."""
        self.print_manual(include_help=False)

    def run(self) -> None:
        """Runs the interactive REPL (Read-Eval-Print Loop) until user exits."""
        self.show_position_summary()

        try:
            while True:
                try:
                    action, text = read_user_action("> ")
                except (EOFError, KeyboardInterrupt):
                    exit_cli()

                if action == "QUIT":
                    exit_cli()

                elif action == "CLEAR":
                    console.clear()
                    continue

                elif action == "RESET":
                    self.cmd_restart()
                    continue

                elif action == "HELP":
                    self.print_help()
                    continue

                elif action == "LEFT":
                    prev_board = self.game.prev_ply()
                    if prev_board is not None:
                        self.show_position_summary(stepped=True)
                    else:
                        console.print("[yellow]At beginning of game.[/yellow]")
                    continue

                elif action == "RIGHT":
                    next_board = self.game.next_ply()
                    if next_board is not None:
                        self.show_position_summary(stepped=True)
                    else:
                        console.print("[yellow]Reached end of game.[/yellow]")
                    continue

                elif action == "COMMAND":
                    if not text:
                        continue

                    user_input = text
                    lowered = user_input.lower()

                    if lowered in ("quit", "/quit"):
                        exit_cli()

                    elif lowered in ("reset", "/reset", "restart", "/restart"):
                        self.cmd_restart()
                        continue

                    elif lowered == "clear":
                        console.clear()
                        continue

                    elif lowered in ("serve", "/serve"):
                        self.cmd_serve()
                        continue

                    elif lowered in ("help", "/help"):
                        self.print_help()
                        continue

                    # Dispatch 3: /eval-short (outputs top engine candidate moves and numerical scores)
                    elif lowered in ("/eval-short", "/eval_short", "/e-short", "eval-short", "eval_short"):
                        self.cmd_eval_short()
                        continue

                    # Dispatch 4: /eval-long (lengthy in-depth paragraph explanation for top engine move)
                    elif lowered in ("/eval-long", "/eval_long", "/e-long", "eval-long", "eval_long"):
                        self.cmd_eval_long()
                        continue

                    # Dispatch 5: /eval (outputs each top line with a short Ollama explanation)
                    elif lowered in ("/eval", "/e", "eval"):
                        self.cmd_eval()
                        continue

                    elif lowered in ("/eval-score", "/eval_score", "eval-score", "eval_score"):
                        self.cmd_eval_score()
                        continue

                    elif lowered in ("/eval-critical", "/eval_critical", "eval-critical", "eval_critical"):
                        self.cmd_eval_critical()
                        continue

                    # Dispatch 6: Step timeline forward (f, forward, n, next)
                    elif lowered in ("f", "forward", "/f", "/forward", "/n", "/next", "n", "next"):
                        next_board = self.game.next_ply()
                        if next_board is not None:
                            self.show_position_summary(stepped=True)
                        else:
                            console.print("[yellow]Reached end of game.[/yellow]")
                        continue

                    # Dispatch 7: Step timeline backward (b, back, backward, p, prev)
                    elif lowered in ("b", "back", "backward", "/b", "/back", "/backward", "/p", "/prev", "p", "prev"):
                        prev_board = self.game.prev_ply()
                        if prev_board is not None:
                            self.show_position_summary(stepped=True)
                        else:
                            console.print("[yellow]At beginning of game.[/yellow]")
                        continue

                    # Dispatch 8: Check for move jump prefix (/jump 7-w, jump 7-w, /m 7-w, etc.)
                    move_num, is_white, remaining_query = GameState.parse_move_prefix_and_query(user_input)
                    if move_num is not None and is_white is not None:
                        try:
                            self.game.jump_to_move(move_num, is_white)
                        except Exception as e:
                            console.print(f"[bold red]Navigation error:[/bold red] {e}")
                            continue

                        if not remaining_query:
                            # User typed only the move specifier: show summary & wait for next turn
                            self.show_position_summary(stepped=True)
                            continue
                        else:
                            # User combined jump with an immediate question: '/jump 7-w, why is h3 bad?'
                            active_ply = self.game.current_ply
                            tag = active_ply.eval_tag if active_ply else f"m{move_num}-{'w' if is_white else 'b'}"
                            move_played = f"Played: {active_ply.san}" if active_ply else ""
                            console.print(f"[dim]Switched to [bold cyan]{tag}[/bold cyan] ({move_played})[/dim]")
                            user_input = remaining_query
                            lowered = user_input.lower()

                    # Dispatch 10: Question with /q <question> or /ask <question>
                    if lowered.startswith("/q ") or lowered.startswith("/ask "):
                        if lowered.startswith("/q "):
                            q_text = user_input[3:].strip()
                        else:
                            q_text = user_input[5:].strip()
                        self.cmd_ask_coach(q_text)

                    # Dispatch 11: General conversational coaching prompt (persists in current move context)
                    else:
                        self.cmd_ask_coach(user_input)

        finally:
            # Crucial: Terminate the Stockfish subprocess when exiting the loop
            self.engine.close()


def prompt_for_pgn() -> str:
    """Interactively prompts the user to paste a PGN or provide a file path.

    When users copy games from Chess.com or Lichess, the PGN contains shell metacharacters
    like curly braces ({[%clk ...]}), parentheses ((8. a4 ...)), brackets ([Event ...]),
    and dollar signs ($4, $6). Pasting directly into a terminal shell like zsh or bash
    causes immediate shell parse errors (e.g. 'zsh: parse error near }').

    Reading from stdin directly inside Python bypasses the shell parser completely,
    allowing safe multi-line pasting, piped input (pbpaste | ./start), or entering
    a file path.
    """
    if not sys.stdin.isatty():
        # Input was piped into stdin (e.g. `cat game.pgn | ./start` or `pbpaste | ./start`)
        content = sys.stdin.read().strip()
        if sys.platform != "win32":
            try:
                sys.stdin = open("/dev/tty")
            except Exception:
                pass
        return content

    move_pattern = re.compile(r"\b1\s*(?:\.{1,3}|(?=\s+[a-zA-Z\u2654-\u265F]))")
    result_pattern = re.compile(r"(?:1-0|0-1|1/2-1/2|\*)\s*$")

    # Step 1: Auto-detect if user recently copied a PGN to their system clipboard (e.g. via Chess.com or Lichess).
    # This prevents users from needing to paste complex multi-line text into the shell, completely avoiding
    # shell parse errors like `zsh: parse error near }` caused by unquoted curly braces or parenthesis.
    if sys.platform == "darwin":
        try:
            res = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=1)
            if res.returncode == 0 and res.stdout.strip():
                clip_text = res.stdout.strip()
                if move_pattern.search(clip_text) or "[Event " in clip_text or "[Site " in clip_text:
                    console.print("[bold green]✓ Loaded PGN directly from clipboard.[/bold green]")
                    return clip_text
        except Exception:
            pass

    console.print(
        Panel(
            "[bold cyan]♟  DUPONT CHESS COACH  ♟[/bold cyan]\n\n"
            "Paste your PGN below (or enter a path to a .pgn file).\n"
            "[dim]Press Enter after pasting (or Ctrl+D when finished):[/dim]",
            title_align="left",
            border_style="cyan",
        )
    )

    lines: list[str] = []
    has_moves = False

    while True:
        try:
            line = sys.stdin.readline()
        except (EOFError, KeyboardInterrupt):
            break

        if not line:  # EOF (Ctrl+D)
            break

        # Check if first non-empty input is an existing file path
        if not lines and line.strip():
            candidate = line.strip()
            if "\n" not in candidate and len(candidate) < 260:
                try:
                    if Path(candidate).is_file():
                        return candidate
                except OSError:
                    pass

        lines.append(line)
        stripped = line.strip()

        if not has_moves and move_pattern.search(line):
            has_moves = True

        if has_moves:
            # Empty line after moves were seen signals end of input
            if not stripped:
                break
            # Standard game result marker terminates the PGN movetext
            if result_pattern.search(stripped):
                break

    return "".join(lines).strip()


def main() -> None:
    """CLI argument entry point."""
    parser = argparse.ArgumentParser(
        description="Interactive Terminal CLI Chess Coaching Tool."
    )
    parser.add_argument(
        "pgn_path",
        nargs="*",
        default=[],
        help="Path to PGN file, literal pasted PGN string, or omit to paste interactively.",
    )
    args = parser.parse_args()

    if not args.pgn_path:
        pgn_input = prompt_for_pgn()
        if not pgn_input:
            console.print("[yellow]No PGN provided. Exiting.[/yellow]")
            sys.exit(0)
    elif len(args.pgn_path) == 1:
        pgn_input = args.pgn_path[0]
    else:
        first_arg = args.pgn_path[0]
        is_first_file = False
        if "\n" not in first_arg and len(first_arg) < 260:
            try:
                is_first_file = Path(first_arg).is_file()
            except OSError:
                is_first_file = False

        if is_first_file:
            pgn_input = first_arg
        else:
            pgn_input = " ".join(args.pgn_path)

    app = ChessCLIApp(pgn_input)
    app.run()


if __name__ == "__main__":
    main()

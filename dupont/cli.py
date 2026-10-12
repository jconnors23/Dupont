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
   - Displays position summary in the 5-line format:
       current move: move <number-player> to go
       previous move: <color> played <san>
       Top Engine Suggestion: (move here)
       Current Eval Score: +0.5
       FEN: Fen

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
     * `/eval-short`: Queries Stockfish for top candidate moves and evaluations.
     * `/eval`: Queries Stockfish for top lines and queries Ollama for a short description of
       why each move is suggested at this time in the current game state.
     * `/eval-long`: Sends ONLY the top eval move to Ollama for a lengthy in-depth paragraph
       explanation of why the engine suggests that decision.
     * Natural Language Question: Automatically detects if a candidate move or the
       played move is referenced, gathers engine facts, and streams GM coaching advice.
     * `/q` / `/exit`: Breaks loop and triggers deterministic engine shutdown.
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
import sys
from pathlib import Path
from typing import Any, Optional

import chess
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from dupont.coach import ChessCoach
from dupont.pgn_cleaner import clean_pgn_file
from dupont.config import config
from dupont.engine import StockfishEngine
from dupont.game_state import GameState

# Console singleton used for all rich terminal I/O
console = Console()


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
        if trimmed.lower() in ("/q", "/quit", "/exit", "q", "quit", "exit"):
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

            # Single-key shortcuts when buffer is empty:
            # 'f' / 'F' -> move forward (next move)
            # 'b' / 'B' -> move backward (previous move)
            # 'n' / 'N' -> next move
            # 'p' / 'P' -> previous move
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
    )
    table.add_column("Rank", justify="center", style="dim")
    for file_char in "a b c d e f g h".split():
        table.add_column(file_char, justify="center")

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


class ChessCLIApp:
    """Coordinates the interactive REPL lifecycle, engine communication, and coaching responses.

    This class serves as the 'Controller' in an MVC-style pattern:
    - Model: GameState and StockfishEngine
    - View: Rich Console, Panels, Tables
    - Controller: REPL dispatch loop in run()
    """

    def __init__(self, pgn_path: str) -> None:
        self.pgn_path = Path(pgn_path)
        if not self.pgn_path.exists():
            console.print(f"[bold red]Error:[/bold red] File not found: {pgn_path}")
            sys.exit(1)

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

    def print_welcome_banner(self) -> None:
        """Displays startup manual with f/b navigation keys and slash commands."""
        manual = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan", padding=(0, 2))
        manual.add_column("Key / Cmd", style="bold yellow", width=24)
        manual.add_column("What it does", style="white")

        manual.add_row("f (or →)", "Step forward to next move")
        manual.add_row("b (or ←)", "Step backward to previous move")
        manual.add_row("/jump 7-w (or 8-b)", "Hop to move (e.g. '/jump 7-w' or '/jump 8-b')")
        manual.add_row("/jump 7-w, <question>", "Hop & ask in one turn (e.g. '/jump 7-w, why is h3 bad?')")
        manual.add_row("/eval-short", "Show top engine candidate moves and numerical scores")
        manual.add_row("/eval", "Show top engine lines with short Ollama explanations")
        manual.add_row("/eval-long", "In-depth paragraph explanation for top engine move")
        manual.add_row("/q <question>", "Ask coach about active move (or type question directly)")
        manual.add_row("/q (or /quit)", "Exit coaching session")

        console.print(
            Panel(
                manual,
                title="[bold cyan]♟  CHESS COACH - QUICK MANUAL  ♟[/bold cyan]",
                subtitle="[dim]Press 'f' for next move, 'b' for previous move | /help for commands[/dim]",
                border_style="cyan",
            )
        )

    def get_position_ui_lines(self) -> list[str]:
        """Formats the position metadata into the required 5-line format.

        Format:
        1. current move: move <number-player> to go
        2. previous move: <color> played <san>
        3. Top Engine Suggestion: (move here)
        4. Current Eval Score: +0.5
        5. FEN: Fen

        Pedagogical note for a CS sophomore:
        When navigating a chess game chronologically:
        - 'current move' identifies which player's turn it is to act right now,
          using standard review move-addressing syntax (e.g. 'move 1-b to go'
          meaning fullmove 1, Black's turn).
        - 'previous move' identifies the half-move that was just executed on the board
          leading up to this exact position (e.g., 'white played e4' or 'black played nc6').
        - 'Top Engine Suggestion' is Stockfish's top evaluated candidate move
          for the active player from this position.
        - 'Current Eval Score' is the deterministic engine centipawn/mate score.
        - 'FEN' is the standard Forsyth-Edwards Notation string capturing the full board state.
        """
        board = self.game.current_board

        # 1. current move: move <number-player> to go
        player_char = "w" if board.turn == chess.WHITE else "b"
        current_move_str = f"current move: move {board.fullmove_number}-{player_char} to go"

        # 2. previous move: <color> played <san>
        idx = self.game.current_ply_index
        if idx == 0 or not self.game.plies:
            prev_move_str = "previous move: none"
        else:
            prev_ply = self.game.plies[idx - 1]
            color_str = "white" if prev_ply.is_white else "black"
            prev_move_str = f"previous move: {color_str} played {prev_ply.san.lower()}"

        # 3 & 4. Stockfish analysis: Top Engine Suggestion & Current Eval Score
        analysis = self.engine.analyze_position(board, depth=14, multipv=1)
        best_move = analysis.get("best_move") or "none"
        best_score = analysis.get("best_eval", "0.00")
        suggestion_str = f"Top Engine Suggestion: {best_move}"
        eval_score_str = f"Current Eval Score: {best_score}"

        # 5. FEN: Fen
        fen_str = f"FEN: {board.fen()}"

        return [current_move_str, prev_move_str, suggestion_str, eval_score_str, fen_str]

    def get_position_ui_text(self) -> str:
        """Returns the 5-line formatted UI as a single string."""
        return "\n".join(self.get_position_ui_lines())

    def show_position_summary(self) -> None:
        """Displays position summary according to the required 5-line UI format."""
        for line in self.get_position_ui_lines():
            console.print(line)

    def cmd_jump_move(self, arg: str) -> None:
        """Navigates to a specific move in the game timeline (e.g. '14', '14w', '14b')."""
        try:
            move_num, is_white = GameState.parse_move_specifier(arg)
            self.game.jump_to_move(move_num, is_white)
            self.show_position_summary()
        except Exception as e:
            console.print(f"[bold red]Navigation error:[/bold red] {e}")

    def cmd_eval_short(self) -> None:
        """Executes a Multi-PV search (depth 16) and renders the top candidate moves in a table."""
        board = self.game.current_board
        with console.status("[cyan]Computing top candidate lines with Stockfish (depth 16)...[/cyan]"):
            analysis = self.engine.analyze_position(board, depth=16, multipv=2)

        table = Table(
            title=f"Stockfish Evaluation - Top Candidate Lines ({'White' if board.turn == chess.WHITE else 'Black'} to move)",
            box=box.ROUNDED,
            header_style="bold magenta",
        )
        table.add_column("#", justify="center", style="dim", width=4)
        table.add_column("Move", justify="center", style="bold cyan", width=10)
        table.add_column("Eval (White POV)", justify="center", width=18)
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

            panel_text = (
                f"[bold cyan]Line {rank}: {move_san}[/bold cyan] (Eval: {score})\n"
                f"[dim]Continuation: {pv_str}[/dim]\n\n"
                f"{explanation.strip()}"
            )
            console.print(
                Panel(
                    panel_text,
                    title=f"[bold]Candidate Move {rank}: {move_san}[/bold]",
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

        summary_text = (
            f"[bold green]Top Move:[/bold green] [bold cyan]{move_san}[/bold cyan] (Eval: {score})\n"
            f"[dim]Continuation: {pv_str}[/dim]\n\n"
            f"{explanation.strip()}"
        )
        console.print(
            Panel(
                Markdown(summary_text),
                title=f"[bold green]In-Depth Top Move Analysis: {move_san}[/bold green]",
                subtitle="[dim]Comprehensive Evaluation Explanation[/dim]",
                border_style="green",
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
                border_style="red",
            )
        )

        # Trigger conversational coach explanation
        with console.status("[magenta]Coach analyzing tactical motifs...[/magenta]"):
            user_q = f"Why couldn't I play {refutation['candidate_san']} in this position?"
            coach_reply = self.coach.chat(user_q, refutation)

        console.print(Panel(Markdown(coach_reply), title="[bold green]Grandmaster Coach Analysis[/bold green]", border_style="green"))

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

        console.print(Panel(Markdown(reply), title="[bold green]Grandmaster Coach[/bold green]", border_style="green"))

    def print_help(self) -> None:
        """Displays reference table of the core available commands."""
        self.print_welcome_banner()

    def run(self) -> None:
        """Runs the interactive REPL (Read-Eval-Print Loop) until user exits."""
        self.print_welcome_banner()
        self.show_position_summary()

        try:
            while True:
                try:
                    action, text = read_user_action("> ")
                except (EOFError, KeyboardInterrupt):
                    console.print("\n[dim]Exiting...[/dim]")
                    break

                if action == "QUIT":
                    console.print("[green]Thanks for analyzing! Good luck in your games.[/green]")
                    break

                elif action == "LEFT":
                    prev_board = self.game.prev_ply()
                    if prev_board is not None:
                        self.show_position_summary()
                    else:
                        console.print("[yellow]At beginning of game.[/yellow]")
                    continue

                elif action == "RIGHT":
                    next_board = self.game.next_ply()
                    if next_board is not None:
                        self.show_position_summary()
                    else:
                        console.print("[yellow]Reached end of game.[/yellow]")
                    continue

                elif action == "COMMAND":
                    if not text:
                        continue

                    user_input = text
                    lowered = user_input.lower()

                    # Dispatch 1: Clean exit (/q, /quit, /exit, q, quit, exit)
                    if lowered in ("/q", "/quit", "/exit", "q", "quit", "exit"):
                        console.print("[green]Thanks for analyzing! Good luck in your games.[/green]")
                        break

                    # Dispatch 2: Help reference (/help, /h, help, ?)
                    elif lowered in ("/help", "/h", "help", "?"):
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

                    # Dispatch 6: Step timeline forward (f, forward, n, next)
                    elif lowered in ("f", "forward", "/f", "/forward", "/n", "/next", "n", "next"):
                        next_board = self.game.next_ply()
                        if next_board is not None:
                            self.show_position_summary()
                        else:
                            console.print("[yellow]Reached end of game.[/yellow]")
                        continue

                    # Dispatch 7: Step timeline backward (b, back, backward, p, prev)
                    elif lowered in ("b", "back", "backward", "/b", "/back", "/backward", "/p", "/prev", "p", "prev"):
                        prev_board = self.game.prev_ply()
                        if prev_board is not None:
                            self.show_position_summary()
                        else:
                            console.print("[yellow]At beginning of game.[/yellow]")
                        continue

                    # Dispatch 8: Clear chat memory (/reset, reset)
                    elif lowered in ("/reset", "reset"):
                        self.coach.reset_history()
                        console.print("[green]Coach conversation history reset.[/green]")
                        continue

                    # Dispatch 9: Check for move jump prefix (/jump 7-w, jump 7-w, /m 7-w, etc.)
                    move_num, is_white, remaining_query = GameState.parse_move_prefix_and_query(user_input)
                    if move_num is not None and is_white is not None:
                        try:
                            self.game.jump_to_move(move_num, is_white)
                        except Exception as e:
                            console.print(f"[bold red]Navigation error:[/bold red] {e}")
                            continue

                        if not remaining_query:
                            # User typed only the move specifier: show summary & wait for next turn
                            self.show_position_summary()
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


def main() -> None:
    """CLI argument entry point."""
    parser = argparse.ArgumentParser(
        description="Interactive Terminal CLI Chess Coaching Tool."
    )
    parser.add_argument("pgn_path", help="Path to PGN file to review.")
    args = parser.parse_args()

    app = ChessCLIApp(args.pgn_path)
    app.run()


if __name__ == "__main__":
    main()

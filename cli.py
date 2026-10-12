#!/usr/bin/env python3
"""cli.py - Interactive Terminal Chess Coaching REPL.

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
   - An initial position summary is printed (Game metadata, Ply 1, FEN, material count,
     and initial Stockfish score).

2. THE REPL EVENT LOOP (`run()`):
   - READ: Prompts the student with the current move context (e.g. `Move 14b > `).
   - EVAL: Parses the command input against known dispatch patterns:
     * `m <num>[w|b]` / `move <num>`: Jumps timeline to that move, updates the board,
       and recalculates the evaluation badge.
     * `n` / `p`: Increments/decrements the current ply by 1 (like arrow keys).
     * `board`: Renders a 2D styled ASCII/Unicode board in the terminal.
     * `eval`: Queries Stockfish for Multi-PV top 3 candidate moves and lines.
     * `why not <move>`: Runs `engine.refute_candidate()`, displays the refutation
       card, and triggers the LLM coach to explain why the move fails.
     * Natural Language Question: Automatically detects if a candidate move or the
       played move is referenced, gathers engine facts, and streams GM coaching advice.
     * `q` / `exit`: Breaks loop and triggers deterministic engine shutdown.
   - PRINT: Renders output using `rich` terminal panels, markdown, and tables.
   - LOOP: Repeats until user exits or sends EOF (Ctrl+D).

3. RESOURCE CLEANUP:
   - Implements a `finally` block ensuring `self.engine.close()` is called, preventing
     orphaned Stockfish subprocesses from running in the background.
"""

from __future__ import annotations

import argparse
import re
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

from agent.coach import ChessCoach
from core.config import config
from core.engine import StockfishEngine
from core.game_state import GameState

# Console singleton used for all rich terminal I/O
console = Console()


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

        # Step 1: Parse and index the PGN game
        try:
            self.game = GameState(self.pgn_path)
        except Exception as e:
            console.print(f"[bold red]Failed to load PGN:[/bold red] {e}")
            sys.exit(1)

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
        """Displays startup manual with the core 5 slash commands."""
        manual = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan", padding=(0, 2))
        manual.add_column("#", style="dim", width=3)
        manual.add_column("Command", style="bold yellow", width=25)
        manual.add_column("What it does", style="white")

        manual.add_row("1", "/m 7-w (or /m 7-b)", "Hop to move (e.g. '/m 7-w' or '/m 8-b')")
        manual.add_row("2", "/q <question>", "Ask coach about active move (or type question directly)")
        manual.add_row("", "/m 7-w, <question>", "Hop & ask in one turn (e.g. '/m 7-w, why is h3 bad?')")
        manual.add_row("3", "/w <move>", "Refute alternative move (e.g. '/w e5', '/w Nxd4')")
        manual.add_row("4", "/eval", "Show Stockfish top 2 lines & evaluations")
        manual.add_row("5", "/q (or /quit)", "Exit coaching session")

        console.print(
            Panel(
                manual,
                title="[bold cyan]♟  CHESS COACH - QUICK MANUAL  ♟[/bold cyan]",
                subtitle="[dim]Designed for split-screen review alongside Chess.com[/dim]",
                border_style="cyan",
            )
        )

    def show_position_summary(self) -> None:
        """Displays position metadata: active move, FEN, material count, and quick engine evaluation."""
        ply = self.game.current_ply
        board = self.game.current_board
        mat = self.game.get_material_count()

        # Compute a fast evaluation of the current position (depth 14)
        with console.status("[cyan]Evaluating position with Stockfish...[/cyan]"):
            analysis = self.engine.analyze_position(board, depth=14, multipv=1)

        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold yellow")
        grid.add_column()

        if ply:
            grid.add_row(
                "Move:",
                f"[bold cyan]{ply.eval_tag}[/bold cyan] ({ply.color_name}) - "
                f"Played: [bold green]{ply.san}[/bold green] ({ply.uci})",
            )
        else:
            grid.add_row("Move:", "Start position")

        grid.add_row("Turn:", f"{'White' if board.turn == chess.WHITE else 'Black'} to move")
        grid.add_row("Material:", str(mat["display"]))

        best_score = analysis.get("best_eval", "0.00")
        best_move = analysis.get("best_move", "N/A")

        eval_line = Text("Eval: ")
        eval_line.append_text(get_eval_badge(best_score))
        eval_line.append(" (White POV) | Stockfish Best: ")
        eval_line.append(best_move, style="bold green")
        grid.add_row("Engine:", eval_line)
        grid.add_row("FEN:", f"[dim]{board.fen()}[/dim]")

        console.print(
            Panel(
                grid,
                title=f"[bold]Position @ Ply {self.game.current_ply_index + 1}/{self.game.total_plies}[/bold]",
                border_style="blue",
            )
        )

    def cmd_jump_move(self, arg: str) -> None:
        """Navigates to a specific move in the game timeline (e.g. '14', '14w', '14b')."""
        try:
            move_num, is_white = GameState.parse_move_specifier(arg)
            self.game.jump_to_move(move_num, is_white)
            self.show_position_summary()
        except Exception as e:
            console.print(f"[bold red]Navigation error:[/bold red] {e}")

    def cmd_eval(self) -> None:
        """Executes a Multi-PV search (depth 16) and renders the top 2 lines in a table."""
        board = self.game.current_board
        with console.status("[cyan]Computing top 2 candidate lines (depth 16)...[/cyan]"):
            analysis = self.engine.analyze_position(board, depth=16, multipv=2)

        table = Table(
            title=f"Stockfish Evaluation - Top 2 Lines ({'White' if board.turn == chess.WHITE else 'Black'} to move)",
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
                    ply = self.game.current_ply
                    prompt_label = (
                        f"[bold cyan][{ply.eval_tag}][/bold cyan] > "
                        if ply
                        else "[bold cyan][m1-w][/bold cyan] > "
                    )
                    user_input = console.input(prompt_label).strip()
                except (EOFError, KeyboardInterrupt):
                    console.print("\n[dim]Exiting...[/dim]")
                    break

                if not user_input:
                    continue

                lowered = user_input.lower()

                # Dispatch 1: Clean exit (/q, /quit, /exit, q, quit, exit)
                if lowered in ("/q", "/quit", "/exit", "q", "quit", "exit"):
                    console.print("[green]Thanks for analyzing! Good luck in your games.[/green]")
                    break

                # Dispatch 2: Help reference (/help, /h, help, ?)
                elif lowered in ("/help", "/h", "help", "?"):
                    self.print_help()
                    continue

                # Dispatch 3: Render board (/board, /b, board)
                elif lowered in ("/board", "/b", "board"):
                    ply = self.game.current_ply
                    last_m = ply.move if ply else None
                    console.print(render_board(self.game.current_board, last_m))
                    continue

                # Dispatch 4: Multi-PV positional evaluation (/eval, /e, eval)
                elif lowered in ("/eval", "/e", "eval"):
                    self.cmd_eval()
                    continue

                # Dispatch 5: Step timeline forward (/n, n, next)
                elif lowered in ("/n", "/next", "n", "next"):
                    next_board = self.game.next_ply()
                    if next_board:
                        self.show_position_summary()
                    else:
                        console.print("[yellow]Reached end of game.[/yellow]")
                    continue

                # Dispatch 6: Step timeline backward (/p, p, prev)
                elif lowered in ("/p", "/prev", "p", "prev"):
                    prev_board = self.game.prev_ply()
                    if prev_board:
                        self.show_position_summary()
                    else:
                        console.print("[yellow]At beginning of game.[/yellow]")
                    continue

                # Dispatch 7: Clear chat memory (/reset, reset)
                elif lowered in ("/reset", "reset"):
                    self.coach.reset_history()
                    console.print("[green]Coach conversation history reset.[/green]")
                    continue

                # Dispatch 8: Check for move navigation prefix (/m 7-w, m7-w, etc.)
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
                        # User combined move hop with an immediate question: '/m 7-w, why is h3 bad?'
                        active_ply = self.game.current_ply
                        tag = active_ply.eval_tag if active_ply else f"m{move_num}-{'w' if is_white else 'b'}"
                        move_played = f"Played: {active_ply.san}" if active_ply else ""
                        console.print(f"[dim]Switched to [bold cyan]{tag}[/bold cyan] ({move_played})[/dim]")
                        user_input = remaining_query
                        lowered = user_input.lower()

                # Dispatch 9: Candidate move refutation (/w <move>, /why <move>, why not <move>)
                if lowered.startswith("/w ") or lowered.startswith("/why ") or lowered.startswith("why not "):
                    if lowered.startswith("/w "):
                        cand_str = user_input[3:].strip()
                    elif lowered.startswith("/why not "):
                        cand_str = user_input[9:].strip()
                    elif lowered.startswith("/why "):
                        cand_str = user_input[5:].strip()
                    else:
                        cand_str = user_input[8:].strip()
                    self.cmd_refute(cand_str)

                # Dispatch 10: Question with /q <question> or /ask <question>
                elif lowered.startswith("/q ") or lowered.startswith("/ask "):
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

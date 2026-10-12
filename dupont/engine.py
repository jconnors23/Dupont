"""core/engine.py - Stockfish UCI Engine Integration and Tactical Refutation.

==============================================================================
END-TO-END FLOW & PURPOSE:
==============================================================================
This module is the deterministic computational backbone of the coaching tool.
In classical software architecture, Large Language Models (LLMs) are notorious
for hallucinating tactical lines, confusing piece coordinates, or suggesting
illegal moves when evaluating chess boards.

To prevent hallucinations entirely, we enforce a strict separation of concerns:
1. STOCKFISH does ALL the heavy mathematical computation:
   - Evaluates piece mobility, king safety, and tactics via alpha-beta search.
   - Calculates exact centipawn scores (100 centipawns = 1 pawn advantage).
   - Identifies Principal Variations (PV) — the optimal sequence of moves.
2. THIS MODULE acts as the abstraction layer:
   - Spawns and manages the Stockfish engine process over the standard UCI
     (Universal Chess Interface) text protocol using standard I/O pipes.
   - Converts raw engine data into clean Python dictionaries.
   - Calculates refutations and evaluation deltas for candidate moves.
3. THE COACH (LLM) only receives these verified, deterministic facts to explain
   tactical motifs conceptually in natural English.

THE REFUTATION ALGORITHM:
When a student asks "Why couldn't I play candidate move M?":
Step 1: Legality Check - Verify candidate move M is in `board.legal_moves`.
Step 2: Baseline Analysis - Search the original board to find the engine's best
        move (B) and its baseline score (Eval_B).
Step 3: Board Cloning - Clone the board (`board.copy()`) and push candidate move M.
Step 4: Punishing Line - Search the cloned board from the opponent's perspective.
        The opponent's top move is the refutation, and their PV is the punishing line.
Step 5: Eval Delta - Calculate the score drop (Eval_after - Eval_B). If the drop
        is >= 2.00 pawns, it is classified as a Blunder; >= 0.80 pawns as a Mistake.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import chess
import chess.engine

from dupont.config import config

logger = logging.getLogger(__name__)


def format_pov_score(score: chess.engine.PovScore) -> str:
    """Formats a chess.engine.PovScore into a human-readable string.

    For a sophomore CS student:
    In chess engines, scores are represented in two forms:
    1. Centipawns (cp): 1 pawn = 100 centipawns. E.g., +150 cp means a 1.5 pawn advantage.
    2. Forced Mate (#): E.g., #+3 means White forces checkmate in 3 moves; #-2 means
       Black forces checkmate in 2 moves.
    """
    if score.is_mate():
        moves_to_mate = score.mate()
        if moves_to_mate is not None:
            sign = "+" if moves_to_mate > 0 else ""
            return f"#{sign}{moves_to_mate}"
        return "#"
    cp = score.score()
    if cp is not None:
        sign = "+" if cp > 0 else ""
        return f"{sign}{cp / 100:.2f}"
    return "0.00"


def score_to_cp_or_none(score: chess.engine.PovScore) -> Optional[int]:
    """Extracts integer centipawns from a PovScore, or None if the score is checkmate."""
    if score.is_mate():
        return None
    return score.score()


class StockfishEngine:
    """Manages an active UCI Stockfish subprocess for positional analysis and refutations.

    In operating systems, Stockfish is an external C++ binary that communicates via
    standard input and output (stdin/stdout) following the Universal Chess Interface (UCI)
    protocol. `chess.engine.SimpleEngine` handles the process lifecycle and pipe I/O.
    """

    def __init__(self, stockfish_path: Optional[str] = None) -> None:
        path = stockfish_path or config.STOCKFISH_PATH
        try:
            # Fork/exec the Stockfish binary as a child subprocess
            self.engine: chess.engine.SimpleEngine = chess.engine.SimpleEngine.popen_uci(path)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to start Stockfish engine at '{path}'. "
                f"Verify the binary path in your .env or system PATH."
            ) from exc

    def close(self) -> None:
        """Gracefully shuts down the Stockfish subprocess to prevent zombie processes."""
        if hasattr(self, "engine") and self.engine is not None:
            try:
                self.engine.quit()
            except Exception:
                pass

    def __enter__(self) -> StockfishEngine:
        """Context manager support (e.g. `with StockfishEngine() as engine:`)."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def _pv_to_san(self, board: chess.Board, moves: list[chess.Move]) -> list[str]:
        """Converts an engine's Principal Variation (PV) move sequence to Standard Algebraic Notation (SAN).

        CS Concept: Why do we need a cloned board here?
        In SAN notation, a move representation like 'Nxd5' or 'Qxf7#' depends on
        the exact board state at the instant that move is played (checking for captures,
        ambiguities, and checks).
        Because the PV contains future moves, we must push each move sequentially onto
        a temporary clone of the board to compute the proper SAN string for each subsequent step.
        """
        temp_board = board.copy()
        san_moves: list[str] = []
        for m in moves:
            if m in temp_board.legal_moves:
                san_moves.append(temp_board.san(m))
                temp_board.push(m)
            else:
                san_moves.append(m.uci())
                break
        return san_moves

    def analyze_position(
        self, board: chess.Board, depth: int = 16, multipv: int = 2
    ) -> dict[str, Any]:
        """Analyzes a board position and returns top candidate lines and evaluation scores.

        Parameters:
            board: The chess.Board to evaluate.
            depth: Search depth limit in plies (default: 16 plies deep).
            multipv: Number of distinct alternative top lines to compute (Multi-PV, default: 2).

        Returns:
            Structured dictionary containing depth, FEN, turn, top lines with scores,
            and the best move.
        """
        # Terminal game states (checkmate or draw) require no engine calculation
        if board.is_game_over():
            result = board.result()
            return {
                "depth": depth,
                "fen": board.fen(),
                "turn": "White" if board.turn == chess.WHITE else "Black",
                "is_check": board.is_check(),
                "is_game_over": True,
                "result": result,
                "lines": [],
                "best_move": None,
                "best_move_uci": None,
                "best_eval": result,
            }

        num_legal = board.legal_moves.count()
        actual_multipv = min(multipv, max(1, num_legal))

        # Instruct Stockfish to search up to `depth` plies, evaluating top `actual_multipv` lines
        info_list = self.engine.analyse(
            board,
            chess.engine.Limit(depth=depth),
            multipv=actual_multipv,
        )

        lines: list[dict[str, Any]] = []
        for rank, entry in enumerate(info_list, start=1):
            pv = entry.get("pv", [])
            if not pv:
                continue

            first_move = pv[0]
            move_san = board.san(first_move) if first_move in board.legal_moves else first_move.uci()
            score_entry: chess.engine.PovScore = entry.get("score")
            score_white = score_entry.white()  # Score normalized from White's POV
            score_rel = score_entry.relative  # Score relative to player whose turn it is

            pv_san = self._pv_to_san(board, pv)
            pv_uci = [m.uci() for m in pv]

            lines.append(
                {
                    "rank": rank,
                    "move": move_san,
                    "uci": first_move.uci(),
                    "score_display": format_pov_score(score_white),
                    "relative_score_display": format_pov_score(score_rel),
                    "score_cp_white": score_to_cp_or_none(score_white),
                    "score_cp_rel": score_to_cp_or_none(score_rel),
                    "is_mate": score_white.is_mate(),
                    "mate_white": score_white.mate(),
                    "pv_san": pv_san,
                    "pv_uci": pv_uci,
                }
            )

        best_line = lines[0] if lines else None
        return {
            "depth": depth,
            "fen": board.fen(),
            "turn": "White" if board.turn == chess.WHITE else "Black",
            "is_check": board.is_check(),
            "is_game_over": False,
            "lines": lines,
            "best_move": best_line["move"] if best_line else None,
            "best_move_uci": best_line["uci"] if best_line else None,
            "best_eval": best_line["score_display"] if best_line else "0.00",
            "best_pv": best_line["pv_san"] if best_line else [],
        }

    def refute_candidate(
        self, board: chess.Board, candidate_move: chess.Move, depth: int = 16
    ) -> dict[str, Any]:
        """Calculates why a candidate move is suboptimal or losing.

        Algorithm Walkthrough:
        1. Verify Legality: A candidate move must be legal in `board`.
        2. Compute Baseline: Find what the engine considers the best move and its score.
        3. Simulate Move: Push `candidate_move` onto a cloned board copy (`board_after`).
        4. Search Counterplay: Analyze `board_after` to find the opponent's best response.
           This response is the exact tactical 'refutation'.
        5. Delta Calculation: Subtract the baseline score from the post-move score to
           measure the loss in evaluation and classify the quality (Blunder, Mistake, Inaccuracy).
        """
        mover_turn = board.turn
        mover_color = "White" if mover_turn == chess.WHITE else "Black"
        opponent_color = "Black" if mover_turn == chess.WHITE else "White"

        # 1. Verify candidate move legality
        if candidate_move not in board.legal_moves:
            return {
                "is_legal": False,
                "error": f"Illegal move '{candidate_move.uci()}' in position {board.fen()}",
                "candidate_san": candidate_move.uci(),
                "candidate_uci": candidate_move.uci(),
                "mover_color": mover_color,
            }

        candidate_san = board.san(candidate_move)
        candidate_uci = candidate_move.uci()

        # 2. Baseline evaluation of the position before the candidate move
        baseline_analysis = self.analyze_position(board, depth=depth, multipv=1)
        best_line = baseline_analysis["lines"][0] if baseline_analysis["lines"] else None
        best_move_san = best_line["move"] if best_line else "None"
        best_move_uci = best_line["uci"] if best_line else "None"
        best_eval_white = best_line["score_display"] if best_line else "0.00"
        best_eval_rel = best_line["relative_score_display"] if best_line else "0.00"
        best_score_cp_rel = best_line["score_cp_rel"] if best_line else 0
        best_is_mate = best_line["is_mate"] if best_line else False

        # 3. Execute candidate move on a cloned board to simulate the future state
        board_after = board.copy()
        board_after.push(candidate_move)

        # 4. Check for immediate terminal state
        if board_after.is_game_over():
            if board_after.is_checkmate():
                return {
                    "is_legal": True,
                    "candidate_san": candidate_san,
                    "candidate_uci": candidate_uci,
                    "mover_color": mover_color,
                    "best_move_san": best_move_san,
                    "best_move_uci": best_move_uci,
                    "best_eval_white": best_eval_white,
                    "after_eval_white": "+#" if mover_turn == chess.WHITE else "-#",
                    "eval_delta_cp": 0,
                    "eval_delta_display": "Checkmate played (Best Move)",
                    "classification": "Best Move (Checkmate)",
                    "punishing_move_san": None,
                    "punishing_line_san": [],
                    "fen_before": board.fen(),
                    "fen_after": board_after.fen(),
                }
            elif board_after.is_stalemate():
                return {
                    "is_legal": True,
                    "candidate_san": candidate_san,
                    "candidate_uci": candidate_uci,
                    "mover_color": mover_color,
                    "best_move_san": best_move_san,
                    "best_move_uci": best_move_uci,
                    "best_eval_white": best_eval_white,
                    "after_eval_white": "0.00",
                    "eval_delta_cp": -best_score_cp_rel if best_score_cp_rel is not None else 0,
                    "eval_delta_display": "Stalemate",
                    "classification": "Stalemate",
                    "punishing_move_san": None,
                    "punishing_line_san": [],
                    "fen_before": board.fen(),
                    "fen_after": board_after.fen(),
                }

        # Find the opponent's best reply to our candidate move
        after_info = self.engine.analyse(board_after, chess.engine.Limit(depth=depth), multipv=1)
        after_line = after_info[0] if after_info else {}
        after_score: chess.engine.PovScore = after_line.get("score")
        after_score_white = after_score.white()
        # POV relative to the player who made the candidate move
        after_score_mover = after_score.pov(mover_turn)

        after_eval_white = format_pov_score(after_score_white)
        after_eval_mover = format_pov_score(after_score_mover)

        punishing_pv = after_line.get("pv", [])
        punishing_pv_san = self._pv_to_san(board_after, punishing_pv)
        punishing_move_san = punishing_pv_san[0] if punishing_pv_san else None

        # 5. Compute the evaluation drop (delta) from mover's perspective
        eval_delta_cp: Optional[int] = None
        eval_delta_display: str = ""
        classification: str = "Good"

        mover_cp_after = score_to_cp_or_none(after_score_mover)

        if best_score_cp_rel is not None and mover_cp_after is not None:
            # Eval delta = score_after_move - score_best_move
            eval_delta_cp = mover_cp_after - best_score_cp_rel
            delta_pawns = eval_delta_cp / 100.0
            eval_delta_display = f"{delta_pawns:+.2f} pawns"

            # Industry-standard chess evaluation thresholds:
            if eval_delta_cp <= -200:
                classification = "Blunder"  # Loss of 2.0+ pawns
            elif eval_delta_cp <= -80:
                classification = "Mistake"  # Loss of 0.8+ pawns
            elif eval_delta_cp <= -30:
                classification = "Inaccuracy"  # Loss of 0.3+ pawns
            elif eval_delta_cp >= 0:
                classification = "Best Move"
            else:
                classification = "Good Move"
        else:
            # Handle transitions involving checkmate
            if after_score_mover.is_mate():
                m = after_score_mover.mate()
                if m is not None and m < 0:
                    classification = "Blunder (Allows Checkmate)"
                    eval_delta_display = f"Allows checkmate in {abs(m)}"
                elif m is not None and m > 0:
                    classification = "Winning"
                    eval_delta_display = f"Forces checkmate in {m}"
            elif best_is_mate:
                classification = "Blunder (Missed Win)"
                eval_delta_display = "Missed forced mate sequence"
            else:
                classification = "Blunder"
                eval_delta_display = "Severe evaluation loss"

        # If the candidate move chosen was actually the best move found
        if candidate_uci == best_move_uci:
            classification = "Best Move"
            if eval_delta_cp is None or eval_delta_cp < 0:
                eval_delta_cp = 0
                eval_delta_display = "0.00 (Best move)"

        return {
            "is_legal": True,
            "candidate_san": candidate_san,
            "candidate_uci": candidate_uci,
            "mover_color": mover_color,
            "opponent_color": opponent_color,
            "best_move_san": best_move_san,
            "best_move_uci": best_move_uci,
            "best_eval_white": best_eval_white,
            "best_eval_relative": best_eval_rel,
            "after_eval_white": after_eval_white,
            "after_eval_relative": after_eval_mover,
            "eval_delta_cp": eval_delta_cp,
            "eval_delta_display": eval_delta_display,
            "classification": classification,
            "punishing_move_san": punishing_move_san,
            "punishing_line_san": punishing_pv_san[:5],
            "fen_before": board.fen(),
            "fen_after": board_after.fen(),
        }

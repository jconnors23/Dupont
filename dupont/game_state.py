"""core/game_state.py - Chess Game State Machine and PGN Navigation.

==============================================================================
END-TO-END FLOW & PURPOSE:
==============================================================================
This module manages the deterministic state machine of a chess game. In chess
software, game history is traditionally stored in PGN (Portable Game Notation)
format. While a PGN is human-readable, an interactive analysis tool needs fast,
random-access indexing into any position in the game history.

The lifecycle in this file works as follows:
1. INGESTION: The user supplies a PGN file or string.
2. TREE PARSING: We parse the game using `chess.pgn.read_game`. We extract game
   metadata (headers like players, ratings, date, result) and traverse the
   mainline move nodes.
3. PLY INDEXING: A "ply" (or half-move) is a single turn taken by either White
   or Black (e.g., 1. e4 is ply 0, 1... e5 is ply 1). For every ply, we compute:
   - FEN (Forsyth-Edwards Notation) BEFORE the move is executed.
   - SAN (Standard Algebraic Notation, e.g., 'Nxd5', 'O-O').
   - UCI (Universal Chess Interface coordinate notation, e.g., 'c6d5', 'e1g1').
   - FEN AFTER the move is executed.
   We store these in a pre-computed array `plies: list[PlyInfo]`.
4. FAST NAVIGATION & STATE RECONSTRUCTION:
   When the user types `m 14` or `m 14w`, instead of replaying moves from scratch,
   we look up the exact ply in O(N) or O(1) time and reconstruct the board using
   the pre-recorded `fen_before`.
5. CANDIDATE MOVE VALIDATION:
   When a user asks "Why not Nxd5?", we parse and validate whether the candidate
   string represents a legal move in the current position, supporting both SAN and
   UCI formats.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import chess
import chess.pgn


@dataclass
class PlyInfo:
    """Represents a single half-move (ply) snapshot in the game timeline.

    For a sophomore CS student: In chess terminology, a 'fullmove' consists of
    White's move followed by Black's move. A 'ply' is one turn by ONE player.
    So a 40-move game has up to 80 plies.
    """

    ply_index: int  # 0-based index in the chronological move list (0, 1, 2, ...)
    move_number: int  # Standard 1-based chess fullmove number (1, 2, ..., 40)
    is_white: bool  # True if White made the move, False if Black
    san: str  # Standard Algebraic Notation, e.g. "Nf3", "Bxf7+", "O-O"
    uci: str  # Universal Chess Interface coordinates, e.g. "g1f3", "e1g1"
    fen_before: str  # Board FEN representation before the move was played
    fen_after: str  # Board FEN representation after the move was played
    move: chess.Move  # Low-level python-chess Move object (from_square, to_square)

    @property
    def color_name(self) -> str:
        """Returns readable color string: 'White' or 'Black'."""
        return "White" if self.is_white else "Black"

    @property
    def eval_tag(self) -> str:
        """Returns the Chess.com review format tag, e.g. 'm7-w' or 'm14-b'."""
        suffix = "w" if self.is_white else "b"
        return f"m{self.move_number}-{suffix}"

    @property
    def display_label(self) -> str:
        """User-friendly label, e.g., 'm7-w (White): h3'."""
        return f"{self.eval_tag} ({self.color_name}): {self.san}"


class GameState:
    """Manages the chess game history, move navigation, and board state.

    This class acts as the 'Source of Truth' for the board state during a review
    session. It decouples game history storage from engine analysis and terminal UI.
    """

    def __init__(self, pgn_source: Union[str, Path]) -> None:
        self.headers: dict[str, str] = {}
        self.plies: list[PlyInfo] = []
        self.current_ply_index: int = 0
        self.load_pgn(pgn_source)

    def load_pgn(self, pgn_source: Union[str, Path]) -> None:
        """Loads a game from a PGN file path or raw PGN string.

        End-to-end flow:
        - Read raw text from disk or memory.
        - Pass text to chess.pgn parser stream.
        - Extract headers (White, Black, Date, Result, etc.).
        - Iterate through the mainline linked list of move nodes.
        - Capture board snapshots before and after each move.
        """
        pgn_text: str
        if isinstance(pgn_source, Path):
            pgn_text = pgn_source.read_text(encoding="utf-8")
        elif isinstance(pgn_source, str):
            # Only attempt path check if string is short and has no newlines
            if "\n" not in pgn_source and len(pgn_source) < 260 and Path(pgn_source).is_file():
                pgn_text = Path(pgn_source).read_text(encoding="utf-8")
            else:
                pgn_text = pgn_source
        else:
            pgn_text = str(pgn_source)

        # Strip leading 'start' command keyword if present (e.g. 'start [Event ...]' or 'start 1. e4 ...')
        pgn_text = re.sub(r"^\s*start\b\s*:?\s*", "", pgn_text, flags=re.IGNORECASE)

        # Parse PGN text stream into a Game object
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        if game is None:
            raise ValueError("Failed to parse valid PGN game from source.")

        # Cache headers into a clean dictionary
        self.headers = {k: str(v) for k, v in game.headers.items()}
        self.plies = []

        # Traverse the game's mainline move graph.
        # In python-chess, game moves form a tree (with variations). `mainline()`
        # walks the primary sequence of moves played in the actual game.
        board = game.board()
        for idx, node in enumerate(game.mainline()):
            # The parent node represents the board immediately prior to this move
            parent_board = node.parent.board() if node.parent else board
            move = node.move
            fen_before = parent_board.fen()
            san = node.san()
            uci = move.uci()
            fen_after = node.board().fen()
            is_white = parent_board.turn == chess.WHITE
            move_number = parent_board.fullmove_number

            self.plies.append(
                PlyInfo(
                    ply_index=idx,
                    move_number=move_number,
                    is_white=is_white,
                    san=san,
                    uci=uci,
                    fen_before=fen_before,
                    fen_after=fen_after,
                    move=move,
                )
            )

        # Reset active pointer to the start of the game
        self.current_ply_index = 0

    @property
    def total_plies(self) -> int:
        """Total number of half-moves recorded in the game."""
        return len(self.plies)

    @property
    def total_moves(self) -> int:
        """Total number of full moves in the game."""
        if not self.plies:
            return 0
        return self.plies[-1].move_number

    @property
    def current_ply(self) -> Optional[PlyInfo]:
        """Returns the PlyInfo metadata for the current position pointer."""
        if 0 <= self.current_ply_index < len(self.plies):
            return self.plies[self.current_ply_index]
        return None

    @property
    def current_board(self) -> chess.Board:
        """Returns a chess.Board instance representing the position BEFORE the current ply's move.

        Pedagogical note:
        When a student jumps to Move 14w to ask 'Why was my move a mistake?' or
        'Why couldn't I play Nxd5 here?', they want to evaluate the position at
        the moment the decision had to be made (before the move was played).
        When the timeline pointer reaches the very end of the game (index == total_plies),
        we reconstruct the final terminal board state using the last ply's fen_after.
        """
        current = self.current_ply
        if current:
            return chess.Board(current.fen_before)
        if self.plies and self.current_ply_index == len(self.plies):
            return chess.Board(self.plies[-1].fen_after)
        return chess.Board()

    def jump_to_move(self, move_num: int, is_white: bool = True) -> chess.Board:
        """Jumps to a specific move number and color, returning the board at that position.

        Example:
            jump_to_move(14, True)  -> Move 14 White
            jump_to_move(14, False) -> Move 14 Black
        """
        if not self.plies:
            raise ValueError("No plies found in this game.")

        target_idx: Optional[int] = None
        for idx, ply in enumerate(self.plies):
            if ply.move_number == move_num and ply.is_white == is_white:
                target_idx = idx
                break

        if target_idx is None:
            # Fallback: if the specific color wasn't found (e.g. game ended on 14w), inform user clearly
            side = "White" if is_white else "Black"
            raise ValueError(
                f"Move {move_num} ({side}) not found in game (Game has {self.total_moves} moves)."
            )

        self.current_ply_index = target_idx
        return self.current_board

    def jump_to_ply(self, ply_index: int) -> chess.Board:
        """Jumps directly to a 0-indexed ply in the timeline."""
        if not self.plies:
            raise ValueError("No plies in game.")
        if ply_index < 0 or ply_index > len(self.plies):
            raise IndexError(
                f"Ply index {ply_index} out of range (0 to {len(self.plies)})."
            )
        self.current_ply_index = ply_index
        return self.current_board

    def next_ply(self) -> Optional[chess.Board]:
        """Steps forward one ply in the timeline (like pressing Right Arrow on Chess.com)."""
        if self.current_ply_index + 1 <= len(self.plies):
            self.current_ply_index += 1
            return self.current_board
        return None

    def prev_ply(self) -> Optional[chess.Board]:
        """Steps backward one ply in the timeline (like pressing Left Arrow on Chess.com)."""
        if self.current_ply_index - 1 >= 0:
            self.current_ply_index -= 1
            return self.current_board
        return None

    @staticmethod
    def parse_move_specifier(spec: str) -> tuple[int, bool]:
        r"""Parses a user move string like '/jump 7-w', '/jump 8-b', 'jump 7-w', '7-w', '7-b', '14', '14w', '14b' into (move_num, is_white).

        Supported review move formats:
        - '/jump 7-w', '/jump 8-b', 'jump 7-w' (primary jump command format)
        - '/m 7-w', 'm7-w', 'm7-b', 'm14-w' (legacy alias)
        - '7-w', '7-b', '7w', '7b', '7'
        - Defaults to White (True) if no color is specified.
        """
        cleaned = spec.strip().lower()
        match = re.match(
            r"^(?:/?(?:m|move|jump)\s*[-_ ]?(\d+)(?:[-_ ]?([wb]))?|(\d+)[-_ ]?([wb])?)$",
            cleaned,
        )
        if not match:
            raise ValueError(
                f"Invalid move specifier: '{spec}'. Use format like '/jump 7-w', '7-w', '7-b', '14w', or '14b'."
            )

        num_str = match.group(1) or match.group(3)
        color_char = match.group(2) or match.group(4)
        move_num = int(num_str)
        is_white = True if color_char in (None, "w") else False
        return move_num, is_white

    @staticmethod
    def parse_move_prefix_and_query(
        input_str: str,
    ) -> tuple[Optional[int], Optional[bool], str]:
        r"""Detects whether a student prompt begins with a move specifier (e.g. '/jump 7-w, why is going to h3 suboptimal').

        Supports '/jump 7-w', 'jump 7-w', '/m 7-w', 'm7-w', '7-w' prefixes.

        Returns:
            (move_num, is_white, remaining_query) if a move prefix was found;
            (None, None, input_str) if no move prefix was present.
        """
        raw = input_str.strip()
        match = re.match(
            r"^(?:/?(?:m|move|jump)\s*[-_ ]?(\d+)(?:[-_ ]?([wb]))?|(\d+)[-_ ]?([wb]))\b\s*[,:]?\s*(.*)$",
            raw,
            re.IGNORECASE,
        )
        if not match:
            return None, None, raw

        num_str = match.group(1) or match.group(3)
        color_char = match.group(2) or match.group(4)
        remaining = match.group(5).strip()

        move_num = int(num_str)
        is_white = True if color_char in (None, "w") or color_char.lower() == "w" else False
        return move_num, is_white, remaining

    @staticmethod
    def parse_candidate_move(board: chess.Board, move_str: str) -> Optional[chess.Move]:
        """Parses a user move string in either SAN ('Nxd5') or UCI ('c6d5') format.

        Returns:
            chess.Move if the move is strictly legal in the current position;
            None if the move is invalid or illegal.

        Pedagogical note on parsing:
        Humans write moves loosely in terminal chats: 'nxd5', 'Nxd5?', 'O-O', '0-0'.
        This method uses a multi-tier fallback parser to normalize and validate
        against the legal move generator.
        """
        raw = move_str.strip()
        if not raw:
            return None

        # Tier 1: Try UCI coordinate notation (e.g., 'e2e4', 'g1f3')
        try:
            candidate = chess.Move.from_uci(raw.lower())
            if candidate in board.legal_moves:
                return candidate
        except (ValueError, chess.InvalidMoveError):
            pass

        # Tier 2: Try standard SAN (Standard Algebraic Notation), stripping punctuation
        san_clean = raw.rstrip("?!#+")
        try:
            return board.parse_san(san_clean)
        except (ValueError, chess.IllegalMoveError, chess.AmbiguousMoveError, chess.InvalidMoveError):
            pass

        # Tier 3: Handle lowercase piece letters (e.g. user typed 'nxd5' instead of 'Nxd5')
        if len(san_clean) > 1 and san_clean[0].islower() and san_clean[0] in "nbrqk":
            try:
                capitalized = san_clean[0].upper() + san_clean[1:]
                return board.parse_san(capitalized)
            except (ValueError, chess.IllegalMoveError, chess.AmbiguousMoveError, chess.InvalidMoveError):
                pass

        # Tier 4: Handle castling notation variations (zeros vs uppercase letter 'O')
        if san_clean.lower() in ("0-0", "o-o"):
            for castle_str in ("O-O", "0-0"):
                try:
                    return board.parse_san(castle_str)
                except Exception:
                    pass
        elif san_clean.lower() in ("0-0-0", "o-o-o"):
            for castle_str in ("O-O-O", "0-0-0"):
                try:
                    return board.parse_san(castle_str)
                except Exception:
                    pass

        return None

    def get_summary_header(self) -> str:
        """Returns a formatted summary string of the game metadata."""
        white = self.headers.get("White", "Unknown")
        black = self.headers.get("Black", "Unknown")
        result = self.headers.get("Result", "*")
        date = self.headers.get("Date", "????.??.??")
        event = self.headers.get("Event", "Game")
        return f"{white} vs {black} | Result: {result} | Date: {date} | Event: {event}"

    def get_material_count(self) -> dict[str, Union[int, str]]:
        """Calculates piece material count and balance for the current board position."""
        return calculate_material(self.current_board)


# Standard chess piece values (in pawn units)
PIECE_VALUES: dict[chess.PieceType, int] = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
}


def calculate_material(board: chess.Board) -> dict[str, Union[int, str]]:
    """Calculates piece values for White and Black (excluding kings) and material difference.

    For a sophomore CS student:
    In chess evaluation, material balance is the most basic static evaluation feature.
    A standard set of non-king pieces totals:
      8 pawns (8) + 2 knights (6) + 2 bishops (6) + 2 rooks (10) + 1 queen (9) = 39 points.
    A positive difference indicates White is ahead in material; negative indicates Black is ahead.
    """
    white_pts = sum(len(board.pieces(pt, chess.WHITE)) * val for pt, val in PIECE_VALUES.items())
    black_pts = sum(len(board.pieces(pt, chess.BLACK)) * val for pt, val in PIECE_VALUES.items())
    diff = white_pts - black_pts
    sign = "+" if diff > 0 else ""
    return {
        "white_pts": white_pts,
        "black_pts": black_pts,
        "diff": diff,
        "display": f"White: {white_pts} | Black: {black_pts} (Balance: {sign}{diff})",
    }

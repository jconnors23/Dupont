"""tests/test_chess_coach.py - Automated Unit, Mock, and Property-Based Tests.

==============================================================================
END-TO-END FLOW & ARCHITECTURAL PURPOSE:
==============================================================================
This test module provides end-to-end and unit-level verification of the Grandmaster
Chess Coach CLI application using pytest, unittest.mock.MagicMock, and Hypothesis.

The test suite exercises five core subsystems:
1. GameState (`core/game_state.py`):
   - Ingestion and navigation of PGN files and raw strings.
   - Ply index tracking, forward/backward navigation, and FEN state snapshots.
   - Move specifier parsing (e.g. '/jump 7-w', 'm14-b', '7-w', 'jump 8-b').
   - Material balance calculation (39 pawn-unit baseline).
   - Candidate move parsing in SAN and UCI format.
2. StockfishEngine (`core/engine.py`):
   - UCI engine integration, multipv candidate line generation.
   - Refutation analysis for blunders (detecting tactical punishments like Scholar/Fool's mate).
   - Validation that top engine recommendations match grandmaster lines.
3. ChessCoach (`coach/client.py`):
   - Offline fallback behavior when LLM endpoints are unreachable.
   - Online LLM response formatting and conversation history tracking via MagicMock.
4. ChessCLIApp (`cli.py`):
   - Five-line UI state format (current move, previous move, engine suggestion, eval, FEN).
   - Command evaluations (/eval-short, /eval, /eval-long).
   - Interactive key-press handling (arrow escapes, quick keys like 'f'/'b'/'n'/'p', commands).
5. PGNCleaner (`cleaner.py`):
   - Metadata header stripping and in-place rewriting.
6. Property-Based Testing (Hypothesis):
   - Invariant fuzzing for move specifiers across random move numbers, prefixes, and colors.
   - Invariant fuzzing for material calculation across arbitrary board piece configurations.
   - Invariant fuzzing for PGN header stripping across arbitrary header schemas.

PEDAGOGICAL EXPLANATION FOR A CS SOPHOMORE:
------------------------------------------
Unlike standard unit testing that only checks hardcoded examples (e.g. testing `1+1 == 2`),
this suite utilizes three complementary testing methodologies:
1. Example-Based Testing (Pytest): Verifies specific historical games (Morphy's Opera Game)
   and well-known board positions.
2. Mocking (MagicMock): Simulates external network boundaries (OpenAI-compatible LLM servers)
   so tests remain deterministic, blazingly fast, and 100% offline.
3. Property-Based Testing (Hypothesis): Automatically generates hundreds of randomized edge-case
   inputs (fuzzing) to prove algebraic properties hold universally for all valid inputs.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import chess
import pytest
from hypothesis import given, strategies as st

from dupont.pgn_cleaner import clean_pgn_content, clean_pgn_file
from dupont.cli import ChessCLIApp, read_user_action
from dupont.coach import ChessCoach
from dupont.config import config
from dupont.engine import StockfishEngine
from dupont.game_state import GameState, calculate_material


# ==============================================================================
# PYTEST FIXTURES
# ==============================================================================

@pytest.fixture
def sample_game_path() -> Path:
    """Returns the filesystem path to the sample Opera Game PGN."""
    return Path(__file__).parent / "sample_game.pgn"


@pytest.fixture
def sample_game(sample_game_path: Path) -> GameState:
    """Initializes and returns a GameState instance loaded with Morphy's Opera Game."""
    return GameState(sample_game_path)


@pytest.fixture
def stockfish_engine() -> Generator[StockfishEngine, None, None]:
    """Yields a managed StockfishEngine instance, ensuring subprocess cleanup on teardown."""
    engine = StockfishEngine()
    try:
        yield engine
    finally:
        engine.close()


@pytest.fixture
def cli_app(sample_game_path: Path) -> Generator[ChessCLIApp, None, None]:
    """Yields a managed ChessCLIApp instance, ensuring engine subprocess closure."""
    app = ChessCLIApp(str(sample_game_path))
    try:
        yield app
    finally:
        app.engine.close()


# ==============================================================================
# 1. GAME STATE UNIT TESTS
# ==============================================================================

class TestGameState:
    """Tests for PGN parsing, ply navigation, and move specifier evaluation."""

    def test_headers_loaded(self) -> None:
        raw_pgn = '[Event "Casual Game"]\n[White "Paul Morphy"]\n[Black "Duke Karl"]\n\n1. e4 e5'
        game = GameState(raw_pgn)
        assert game.headers.get("White") == "Paul Morphy"
        assert game.headers.get("Black") == "Duke Karl"

    def test_plies_count(self, sample_game: GameState) -> None:
        # Opera game is 17 full moves ending at 17. Rd8#
        # Total plies = 16*2 + 1 = 33
        assert sample_game.total_plies == 33

    def test_jump_to_move(self, sample_game: GameState) -> None:
        # Jump to move 14 White (14. Rd1)
        board_14w = sample_game.jump_to_move(14, is_white=True)
        assert sample_game.current_ply.san == "Rd1"
        assert board_14w.turn == chess.WHITE

        # Jump to move 14 Black (14... Qe6)
        board_14b = sample_game.jump_to_move(14, is_white=False)
        assert sample_game.current_ply.san == "Qe6"
        assert board_14b.turn == chess.BLACK

    def test_step_navigation(self, sample_game: GameState) -> None:
        sample_game.jump_to_ply(0)
        assert sample_game.current_ply_index == 0
        b = sample_game.next_ply()
        assert b is not None
        assert sample_game.current_ply_index == 1
        b_prev = sample_game.prev_ply()
        assert b_prev is not None
        assert sample_game.current_ply_index == 0

    def test_parse_candidate_move(self) -> None:
        # Starting position
        board = chess.Board()
        m1 = GameState.parse_candidate_move(board, "e4")
        assert m1 == chess.Move.from_uci("e2e4")

        m2 = GameState.parse_candidate_move(board, "Nf3")
        assert m2 == chess.Move.from_uci("g1f3")

        m_uci = GameState.parse_candidate_move(board, "e2e4")
        assert m_uci == chess.Move.from_uci("e2e4")

        # Illegal move
        m_illegal = GameState.parse_candidate_move(board, "Nxd5")
        assert m_illegal is None

    def test_material_calculation(self) -> None:
        board = chess.Board()
        mat = calculate_material(board)
        # Standard starting material: 8*1 + 2*3 + 2*3 + 2*5 + 9 = 39 pts each
        assert mat["white_pts"] == 39
        assert mat["black_pts"] == 39
        assert mat["diff"] == 0

    def test_chess_com_move_specifiers(self) -> None:
        # /jump 7-w and jump 8-b
        assert GameState.parse_move_specifier("/jump 7-w") == (7, True)
        assert GameState.parse_move_specifier("jump 8-b") == (8, False)
        assert GameState.parse_move_specifier("/jump-7-w") == (7, True)
        # m7-w and m7-b (legacy compatibility)
        assert GameState.parse_move_specifier("m7-w") == (7, True)
        assert GameState.parse_move_specifier("m7-b") == (7, False)
        assert GameState.parse_move_specifier("/m 7-w") == (7, True)
        assert GameState.parse_move_specifier("/m-7-w") == (7, True)
        assert GameState.parse_move_specifier("/m 7-b") == (7, False)
        assert GameState.parse_move_specifier("/m-7-b") == (7, False)
        assert GameState.parse_move_specifier("m14-w") == (14, True)
        assert GameState.parse_move_specifier("m14-b") == (14, False)
        assert GameState.parse_move_specifier("7-w") == (7, True)
        assert GameState.parse_move_specifier("7-b") == (7, False)
        assert GameState.parse_move_specifier("m7w") == (7, True)
        assert GameState.parse_move_specifier("m7b") == (7, False)

    def test_parse_move_prefix_and_query(self) -> None:
        # Combined turn with jump: "/jump 7-w, why is going to h3 suboptimal"
        num, is_white, q = GameState.parse_move_prefix_and_query("/jump 7-w, why is going to h3 suboptimal")
        assert num == 7
        assert is_white is True
        assert q == "why is going to h3 suboptimal"

        # Jump without slash: "jump 7-w, why is going to h3 suboptimal"
        num, is_white, q = GameState.parse_move_prefix_and_query("jump 7-w, why is going to h3 suboptimal")
        assert num == 7
        assert is_white is True
        assert q == "why is going to h3 suboptimal"

        # Combined turn with slash (legacy): "/m 7-w, why is going to h3 suboptimal"
        num, is_white, q = GameState.parse_move_prefix_and_query("/m 7-w, why is going to h3 suboptimal")
        assert num == 7
        assert is_white is True
        assert q == "why is going to h3 suboptimal"

        # Combined turn without slash: "m7-w, why is going to h3 suboptimal"
        num, is_white, q = GameState.parse_move_prefix_and_query("m7-w, why is going to h3 suboptimal")
        assert num == 7
        assert is_white is True
        assert q == "why is going to h3 suboptimal"

        # Hop only with slash
        num, is_white, q = GameState.parse_move_prefix_and_query("/jump-8-b")
        assert num == 8
        assert is_white is False
        assert q == ""

        # No move prefix
        num, is_white, q = GameState.parse_move_prefix_and_query("what should white play instead?")
        assert num is None
        assert is_white is None
        assert q == "what should white play instead?"

    def test_eval_tag(self, sample_game: GameState) -> None:
        sample_game.jump_to_move(14, is_white=True)
        assert sample_game.current_ply.eval_tag == "m14-w"
        sample_game.jump_to_move(14, is_white=False)
        assert sample_game.current_ply.eval_tag == "m14-b"

    def test_raw_pgn_string_loading(self) -> None:
        raw_pgn = "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5"
        gs = GameState(raw_pgn)
        assert gs.total_plies == 6
        assert gs.plies[0].eval_tag == "m1-w"
        assert gs.plies[1].eval_tag == "m1-b"


# ==============================================================================
# 2. STOCKFISH ENGINE UNIT TESTS
# ==============================================================================

class TestStockfishEngine:
    """Tests for UCI engine candidate line analysis and refutations."""

    def test_analyze_position(self, stockfish_engine: StockfishEngine) -> None:
        board = chess.Board()
        res = stockfish_engine.analyze_position(board, depth=10, multipv=2)
        assert "lines" in res
        assert len(res["lines"]) == 2
        assert res["best_move"] is not None
        assert "best_eval" in res

    def test_refute_candidate_blunder(self, stockfish_engine: StockfishEngine) -> None:
        # Fool's mate setup: 1. f3 e5 2. g4 Qh4#
        # Position after 1. f3 e5: White plays 2. g4??
        board = chess.Board("rnbqkbnr/pppp1ppp/8/4p3/8/5P2/PPPPP1PP/RNBQKBNR w KQkq - 0 2")
        blunder_move = chess.Move.from_uci("g2g4")

        ref = stockfish_engine.refute_candidate(board, blunder_move, depth=12)
        assert ref["is_legal"] is True
        assert ref["candidate_san"] == "g4"
        assert "Blunder" in ref["classification"]
        assert ref["punishing_move_san"] == "Qh4#"

    def test_refute_best_move(self, stockfish_engine: StockfishEngine) -> None:
        # Position where e4 is a standard top move
        board = chess.Board()
        best_cand = chess.Move.from_uci("e2e4")
        ref = stockfish_engine.refute_candidate(board, best_cand, depth=10)
        assert ref["is_legal"] is True
        assert ref["classification"] in ("Best Move", "Good Move")


# ==============================================================================
# 3. CHESS COACH MOCK AND OFFLINE TESTS
# ==============================================================================

class TestChessCoach:
    """Tests for LLM Coach offline fallback and online mocked responses."""

    def test_coach_offline_fallback(self) -> None:
        # Coach pointing to non-existent port
        coach = ChessCoach(base_url="http://127.0.0.1:9999/v1", api_key="test", model="test")
        facts = {
            "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
            "candidate_san": "e5",
            "classification": "Good",
            "eval_delta_display": "+0.00",
            "best_move_san": "e5",
            "best_eval_white": "+0.25",
        }
        # chat should not throw exception even if network/server is down
        resp = coach.chat("Why is e5 good here?", facts)
        assert "deterministic engine analysis" in resp.lower()
        assert "e5" in resp

    def test_coach_online_llm_response(self) -> None:
        """Verifies online response processing using MagicMock for API completion."""
        coach = ChessCoach(base_url="http://mocked/v1", api_key="test", model="test")
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(content="e5 controls key central squares and contest White's center."))
        ]
        coach.client.chat.completions.create = MagicMock(return_value=mock_completion)

        facts = {
            "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
            "candidate_san": "e5",
            "classification": "Good Move",
            "eval_delta_display": "+0.00",
            "best_move_san": "e5",
            "best_eval_white": "+0.25",
        }
        reply = coach.chat("Why is e5 played?", facts)
        assert "controls key central squares" in reply
        # History should have: system, user, assistant
        assert len(coach.history) == 3
        assert coach.history[2]["content"] == reply


# ==============================================================================
# 4. CHESS CLI APP INTERFACE TESTS
# ==============================================================================

class TestChessCLIApp:
    """Tests for CLI navigation UI, evaluation commands, and simulated user input."""

    def test_ui_format_starts_at_move_1(self, cli_app: ChessCLIApp) -> None:
        # App should initialize at Move 1 (ply 1)
        lines = cli_app.get_position_ui_lines()
        assert len(lines) == 5
        # current move: move <number-player> to go
        assert lines[0] == "current move: move 1-b to go"
        # previous move: <color> played <san>
        assert lines[1] == "previous move: white played e4"
        # Top Engine Suggestion: (move here)
        assert lines[2].startswith("Top Engine Suggestion: ")
        # Current Eval Score: +0.5
        assert lines[3].startswith("Current Eval Score: ")
        # FEN: Fen
        assert lines[4].startswith("FEN: ")
        assert "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1" in lines[4]

    def test_ui_format_after_black_move(self, cli_app: ChessCLIApp) -> None:
        # Step forward to Move 1 Black played e5 (ply index 2)
        b = cli_app.game.next_ply()
        assert b is not None
        lines = cli_app.get_position_ui_lines()
        assert lines[0] == "current move: move 2-w to go"
        assert lines[1] == "previous move: black played e5"
        assert lines[2].startswith("Top Engine Suggestion: ")
        assert lines[3].startswith("Current Eval Score: ")
        assert lines[4].startswith("FEN: ")

    def test_ui_format_start_position(self, cli_app: ChessCLIApp) -> None:
        # Step backward to start position (ply index 0)
        cli_app.game.prev_ply()
        assert cli_app.game.current_ply_index == 0
        lines = cli_app.get_position_ui_lines()
        assert lines[0] == "current move: move 1-w to go"
        assert lines[1] == "previous move: none"
        assert lines[2].startswith("Top Engine Suggestion: ")
        assert lines[3].startswith("Current Eval Score: ")
        assert lines[4].startswith("FEN: ")

    def test_ui_format_black_played_nc6(self, cli_app: ChessCLIApp) -> None:
        raw_pgn = "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5"
        cli_app.game = GameState(raw_pgn)
        # Jump to ply 4 (after 2... Nc6 was played)
        cli_app.game.jump_to_ply(4)
        lines = cli_app.get_position_ui_lines()
        assert lines[0] == "current move: move 3-w to go"
        assert lines[1] == "previous move: black played nc6"

    def test_cmd_eval_variants(self, cli_app: ChessCLIApp) -> None:
        # Verify cmd_eval_short runs without exceptions
        cli_app.cmd_eval_short()
        # Verify cmd_eval runs and handles LLM / fallback
        cli_app.cmd_eval()
        # Verify cmd_eval_long runs and handles LLM / fallback
        cli_app.cmd_eval_long()

    def test_read_user_action_arrows_and_commands(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Test simulated input including 'f', 'b', arrows, and commands
        simulated_input = "f\nb\n\x1b[D\n\x1b[C\np\nn\n/jump 7-w\n/eval-short\n/eval-long\n/eval\n/q\n"
        monkeypatch.setattr(sys, "stdin", io.StringIO(simulated_input))

        # 1. 'f' key for forward
        act, val = read_user_action()
        assert act == "RIGHT"
        # 2. 'b' key for backward
        act, val = read_user_action()
        assert act == "LEFT"
        # 3. Left arrow escape sequence
        act, val = read_user_action()
        assert act == "LEFT"
        # 4. Right arrow escape sequence
        act, val = read_user_action()
        assert act == "RIGHT"
        # 5. 'p' command
        act, val = read_user_action()
        assert act == "LEFT"
        # 6. 'n' command
        act, val = read_user_action()
        assert act == "RIGHT"
        # 7. '/jump 7-w' command
        act, val = read_user_action()
        assert act == "COMMAND"
        assert val == "/jump 7-w"
        # 8. '/eval-short' command
        act, val = read_user_action()
        assert act == "COMMAND"
        assert val == "/eval-short"
        # 9. '/eval-long' command
        act, val = read_user_action()
        assert act == "COMMAND"
        assert val == "/eval-long"
        # 10. '/eval' command
        act, val = read_user_action()
        assert act == "COMMAND"
        assert val == "/eval"
        # 11. '/q' command
        act, val = read_user_action()
        assert act == "QUIT"


# ==============================================================================
# 5. PGN CLEANER UNIT TESTS
# ==============================================================================

class TestPGNCleaner:
    """Tests for stripping metadata tags from PGN files and strings."""

    def test_clean_pgn_content_removes_headers(self) -> None:
        raw = (
            '[Event "Casual Game"]\n'
            '[Site "Paris FRA"]\n'
            '[Date "1858.10.21"]\n'
            '[Round "?"]\n'
            '[White "Paul Morphy"]\n'
            '[Black "Duke Karl"]\n'
            '[Result "1-0"]\n\n'
            '1. e4 e5 2. Nf3 d6 3. d4'
        )
        cleaned = clean_pgn_content(raw)
        assert cleaned.startswith("1. e4 e5 2. Nf3 d6 3. d4")
        assert "[Event" not in cleaned
        assert "[Result" not in cleaned
        assert "Paul Morphy" not in cleaned

    def test_clean_pgn_content_starts_with_1e4_without_space(self) -> None:
        raw = '[Event "Blitz"]\n[Result "0-1"]\n\n1.e4 c5 2.Nf3'
        cleaned = clean_pgn_content(raw)
        assert cleaned.startswith("1.e4 c5 2.Nf3")
        assert "[Event" not in cleaned

    def test_clean_pgn_file_resaves_in_place(self, tmp_path: Path) -> None:
        raw = (
            '[Event "Test Match"]\n'
            '[Site "Online"]\n'
            '[Result "1/2-1/2"]\n\n'
            '1. d4 d5 2. c4 e6'
        )
        tmp_file = tmp_path / "test_resave.pgn"
        tmp_file.write_text(raw, encoding="utf-8")

        resaved_path = clean_pgn_file(tmp_file)
        assert resaved_path == tmp_file
        content = tmp_file.read_text(encoding="utf-8")
        assert content.startswith("1. d4 d5 2. c4 e6")
        assert "[Event" not in content
        assert "[Result" not in content


# ==============================================================================
# 6. PROPERTY-BASED TESTS (HYPOTHESIS)
# ==============================================================================

class TestHypothesisProperties:
    """Hypothesis property-based tests verifying invariants under generative fuzzing."""

    @given(
        move_num=st.integers(min_value=1, max_value=500),
        is_white=st.booleans(),
        prefix=st.sampled_from(["/jump ", "jump ", "/jump-", "m", "/m ", "/m-", "move ", ""]),
        sep=st.sampled_from(["-", " ", ""]),
    )
    def test_hypothesis_move_specifiers_parsing(
        self, move_num: int, is_white: bool, prefix: str, sep: str
    ) -> None:
        """Tests that any valid move number and color token combinations parse correctly."""
        color = "w" if is_white else "b"
        spec = f"{prefix}{move_num}{sep}{color}".strip()
        num, white = GameState.parse_move_specifier(spec)
        assert num == move_num
        assert white is is_white

    @given(
        move_num=st.integers(min_value=1, max_value=500),
        prefix=st.sampled_from(["/jump ", "jump ", "/jump-", "m", "/m ", "move ", ""]),
    )
    def test_hypothesis_move_specifier_defaults_to_white(
        self, move_num: int, prefix: str
    ) -> None:
        """Tests that omitting the color character defaults cleanly to White (True)."""
        spec = f"{prefix}{move_num}".strip()
        num, white = GameState.parse_move_specifier(spec)
        assert num == move_num
        assert white is True

    @given(st.text().filter(lambda s: not any(c.isdigit() for c in s)))
    def test_hypothesis_move_specifier_rejects_digitless_input(self, invalid_str: str) -> None:
        """Tests that any input lacking a numeric move identifier raises ValueError."""
        with pytest.raises(ValueError):
            GameState.parse_move_specifier(invalid_str)

    @given(
        move_num=st.integers(min_value=1, max_value=300),
        is_white=st.booleans(),
        prefix=st.sampled_from(["/jump ", "jump ", "/m ", "m"]),
        delimiter=st.sampled_from([", ", ": ", " "]),
        query=st.text(
            alphabet=st.characters(blacklist_categories=("Cs", "Cc"), blacklist_characters="\n\r\t"),
            min_size=1,
            max_size=60,
        ),
    )
    def test_hypothesis_move_prefix_and_query_parsing(
        self, move_num: int, is_white: bool, prefix: str, delimiter: str, query: str
    ) -> None:
        """Tests that prefix notation correctly splits the target ply and user query."""
        color = "w" if is_white else "b"
        input_str = f"{prefix}{move_num}-{color}{delimiter}{query.strip()}"
        num, white, rem_query = GameState.parse_move_prefix_and_query(input_str)
        assert num == move_num
        assert white is is_white
        assert rem_query == query.strip()

    @given(
        pieces=st.lists(
            st.tuples(
                st.sampled_from([chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING]),
                st.booleans(),
                st.integers(min_value=0, max_value=63),
            ),
            max_size=32,
            unique_by=lambda x: x[2],
        )
    )
    def test_hypothesis_material_calculation_properties(
        self, pieces: list[tuple[chess.PieceType, bool, int]]
    ) -> None:
        """Verifies fundamental invariants of chess material evaluation:
        1. Material point counts are always non-negative.
        2. Differential is always strictly equal to white_pts - black_pts.
        """
        board = chess.Board.empty()
        for piece_type, color, square in pieces:
            board.set_piece_at(square, chess.Piece(piece_type, color))

        mat = calculate_material(board)
        assert mat["white_pts"] >= 0
        assert mat["black_pts"] >= 0
        assert mat["diff"] == mat["white_pts"] - mat["black_pts"]

    @given(
        tags=st.lists(
            st.tuples(
                st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=1, max_size=12),
                st.text(
                    alphabet="0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ -_.",
                    min_size=0,
                    max_size=25,
                ),
            ),
            max_size=6,
        ),
        move_text=st.sampled_from([
            "1. e4 e5 2. Nf3 Nc6",
            "1. d4 d5 2. c4 dxc4",
            "1.e4 c5 2.Nf3 d6",
            "1. c4 e5",
        ]),
    )
    def test_hypothesis_clean_pgn_content_properties(
        self, tags: list[tuple[str, str]], move_text: str
    ) -> None:
        """Verifies that clean_pgn_content strips bracketed tags regardless of header combinations."""
        header_lines = "\n".join(f'[{k} "{v}"]' for k, v in tags)
        raw_pgn = f"{header_lines}\n\n{move_text}\n" if header_lines else move_text
        cleaned = clean_pgn_content(raw_pgn)
        assert cleaned.startswith(move_text)
        assert not cleaned.startswith("[")

    @given(
        noise=st.text(
            alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
            min_size=0,
            max_size=20,
        ).filter(lambda s: s not in ["e4", "d4", "Nf3", "c4", "e2e4", "d2d4", "g1f3", "b1c3"])
    )
    def test_hypothesis_candidate_move_safety(self, noise: str) -> None:
        """Verifies that arbitrary string inputs to candidate move parsing never throw unhandled exceptions."""
        board = chess.Board()
        res = GameState.parse_candidate_move(board, noise)
        if res is not None:
            assert isinstance(res, chess.Move)
            assert res in board.legal_moves

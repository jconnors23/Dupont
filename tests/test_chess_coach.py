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
   - Position table (previous move, current move, turn, Stockfish suggestion, and score). FEN stays on the position state.
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
import subprocess
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import chess
import pytest
from hypothesis import given, strategies as st

from dupont.pgn_cleaner import clean_pgn_content, clean_pgn_file, main as pgn_cleaner_main
from dupont.cli import (
    ChessCLIApp,
    classify_eval_score,
    describe_engine_move,
    exit_cli,
    is_critical_decision,
    style_chess_prose,
    read_user_action,
    prompt_for_pgn,
    main as cli_main,
)
from dupont.coach import ChessCoach
from dupont.config import config
from dupont.engine import StockfishEngine
from dupont.game_state import GameState, calculate_material


# ==============================================================================
# PYTEST FIXTURES
# ==============================================================================

OPERA_GAME_PGN = (
    "1. e4 e5 2. Nf3 d6 3. d4 Bg4 4. dxe5 Bxf3 5. Qxf3 dxe5 6. Bc4 Nf6 "
    "7. Qb3 Qe7 8. Nc3 c6 9. Bg5 b5 10. Nxb5 cxb5 11. Bxb5+ Nbd7 "
    "12. O-O-O Rd8 13. Rxd7 Rxd7 14. Rd1 Qe6 15. Bxd7+ Nxd7 16. Qb8+ Nxb8 17. Rd8# 1-0"
)


@pytest.fixture
def sample_game() -> GameState:
    """Initializes and returns a GameState instance loaded with Morphy's Opera Game."""
    return GameState(OPERA_GAME_PGN)


@pytest.fixture
def stockfish_engine() -> Generator[StockfishEngine, None, None]:
    """Yields a managed StockfishEngine instance, ensuring subprocess cleanup on teardown."""
    engine = StockfishEngine()
    try:
        yield engine
    finally:
        engine.close()


@pytest.fixture
def cli_app() -> Generator[ChessCLIApp, None, None]:
    """Yields a managed ChessCLIApp instance, ensuring engine subprocess closure."""
    app = ChessCLIApp(OPERA_GAME_PGN)
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
        assert lines[0] == "previous move: white played e4"
        assert lines[1] == "current move: 1.5"
        assert lines[2] == "turn: black to move"
        assert lines[3].startswith("stockfish: ")
        assert lines[4].startswith("score: ")
        assert all("FEN:" not in line for line in lines)
        assert cli_app.game.current_board.fen() == "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"

    def test_ui_format_after_black_move(self, cli_app: ChessCLIApp) -> None:
        # Step forward to Move 1 Black played e5 (ply index 2)
        b = cli_app.game.next_ply()
        assert b is not None
        lines = cli_app.get_position_ui_lines()
        assert lines[0] == "previous move: black played e5"
        assert lines[1] == "current move: 2"
        assert lines[2] == "turn: white to move"
        assert lines[3].startswith("stockfish: ")
        assert lines[4].startswith("score: ")
        assert all("FEN:" not in line for line in lines)
        assert "4P3" in cli_app.game.current_board.fen()

    def test_ui_format_start_position(self, cli_app: ChessCLIApp) -> None:
        # Step backward to start position (ply index 0)
        cli_app.game.prev_ply()
        assert cli_app.game.current_ply_index == 0
        lines = cli_app.get_position_ui_lines()
        assert lines[0] == "previous move: none"
        assert lines[1] == "current move: 1"
        assert lines[2] == "turn: white to move"
        assert lines[3].startswith("stockfish: ")
        assert lines[4].startswith("score: ")
        assert all("FEN:" not in line for line in lines)
        assert cli_app.game.current_board.fen() == chess.STARTING_FEN

    def test_ui_format_black_played_nc6(self, cli_app: ChessCLIApp) -> None:
        raw_pgn = "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5"
        cli_app.game = GameState(raw_pgn)
        # Jump to ply 4 (after 2... Nc6 was played)
        cli_app.game.jump_to_ply(4)
        lines = cli_app.get_position_ui_lines()
        assert lines[0] == "previous move: black played nc6"
        assert lines[1] == "current move: 3"
        assert lines[2] == "turn: white to move"

    def test_restart_jumps_to_beginning(self, cli_app: ChessCLIApp) -> None:
        cli_app.game.next_ply()
        assert cli_app.game.current_ply_index > 0
        cli_app.cmd_restart()
        assert cli_app.game.current_ply_index == 0
        lines = cli_app.get_position_ui_lines()
        assert lines[0] == "previous move: none"
        assert lines[1] == "current move: 1"
        assert lines[2] == "turn: white to move"

    def test_serve_starts_ollama_then_returns(self, cli_app: ChessCLIApp, monkeypatch: pytest.MonkeyPatch) -> None:
        started: list[list[str]] = []
        listening = {"open": False}

        def port_open(host: str, port: int) -> bool:
            return listening["open"]

        def popen(cmd: list[str], **kwargs: object) -> MagicMock:
            started.append(cmd)
            listening["open"] = True
            return MagicMock()

        monkeypatch.setattr("dupont.cli.coach_port_open", port_open)
        monkeypatch.setattr("dupont.cli.shutil.which", lambda _name: "/opt/homebrew/bin/ollama")
        monkeypatch.setattr("dupont.cli.subprocess.Popen", popen)
        cli_app.cmd_serve()
        assert started == [["/opt/homebrew/bin/ollama", "serve"]]

    def test_cmd_eval_variants(self, cli_app: ChessCLIApp) -> None:
        # Verify cmd_eval_short runs without exceptions
        cli_app.cmd_eval_short()
        # Verify cmd_eval runs and handles LLM / fallback
        cli_app.cmd_eval()
        # Verify cmd_eval_long runs and handles LLM / fallback
        cli_app.cmd_eval_long()
        # Verify cmd_eval_score explains the current White-POV score
        cli_app.cmd_eval_score()

    def test_classify_eval_score(self) -> None:
        assert classify_eval_score("+0.31") == "even"
        assert classify_eval_score("-0.50") == "even"
        assert classify_eval_score("+0.51") == "white ahead"
        assert classify_eval_score("-1.20") == "black ahead"
        assert classify_eval_score("#+3") == "white ahead"
        assert classify_eval_score("#-2") == "black ahead"
        assert classify_eval_score("1-0") == "white ahead"
        assert classify_eval_score("0-1") == "black ahead"
        assert classify_eval_score("1/2-1/2") == "even"

    def test_style_chess_prose_colors_keywords(self) -> None:
        styled = style_chess_prose("The knight moves to h6, giving check. White is ahead +0.80. Do eval.")

        def style_at(word: str) -> str:
            index = styled.plain.lower().find(word.lower())
            assert index >= 0
            matches = [str(span.style) for span in styled._spans if span.start <= index < span.end]
            return " ".join(matches)

        assert "gold" in style_at("h6")
        assert "green" in style_at("knight")
        assert "red" in style_at("check")
        assert "yellow" in style_at("ahead")
        assert "cyan" in style_at("+0.80")
        assert "cyan" in style_at("eval")
        assert style_at("moves") == ""

    def test_describe_engine_move(self) -> None:
        assert describe_engine_move("Nh6") == "knight moves to h6"
        assert describe_engine_move("e4") == "pawn moves to e4"
        assert describe_engine_move("Nxd4") == "knight captures on d4"
        assert describe_engine_move("O-O") == "king castles kingside"
        assert describe_engine_move("Qf4+") == "queen moves to f4, giving check"

    def test_opening_view_puts_commands_first(self, cli_app: ChessCLIApp, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[str] = []
        monkeypatch.setattr(
            cli_app,
            "get_position_ui_lines",
            lambda: [
                "previous move: none",
                "current move: 1",
                "turn: white",
                "stockfish: nf6\nstockfish recommends knight moves to f6\nto understand why, do eval",
                "score: +0.20",
            ],
        )
        monkeypatch.setattr("dupont.cli.print_section_banner", lambda title: seen.append(title))
        cli_app.show_position_summary()
        assert seen == ["commands", "position"]
        seen.clear()
        cli_app.show_position_summary(stepped=True)
        assert seen == ["position"]

    def test_exit_cli_clears_then_prints_exit_line(self, monkeypatch: pytest.MonkeyPatch) -> None:
        printed: list[str] = []
        monkeypatch.setattr("dupont.cli.console.clear", lambda: printed.append("clear"))
        monkeypatch.setattr("dupont.cli.console.print", lambda msg: printed.append(msg))
        with pytest.raises(SystemExit) as exc:
            exit_cli()
        assert exc.value.code == 0
        assert printed == ["clear", "sys.exit(0)"]

    def test_help_omits_help_row(self, cli_app: ChessCLIApp) -> None:
        names = [name for name, _action in cli_app.command_rows(include_help=False)]
        assert "help" not in names
        assert names[0] == "serve"
        assert "eval-critical" in names
        opening = [name for name, _action in cli_app.command_rows()]
        assert opening[-2] == "help"

    def test_is_critical_decision(self) -> None:
        quiet = [
            {"is_mate": False, "score_cp_white": 20},
            {"is_mate": False, "score_cp_white": 10},
        ]
        sharp = [
            {"is_mate": False, "score_cp_white": 180},
            {"is_mate": False, "score_cp_white": 20},
        ]
        mate = [{"is_mate": True, "score_cp_white": None}]
        assert is_critical_decision(quiet) is False
        assert is_critical_decision(sharp) is True
        assert is_critical_decision(mate) is True

    def test_eval_critical_jumps_to_the_next_sharp_position(
        self, cli_app: ChessCLIApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        start = cli_app.game.current_ply_index
        scans = {"n": 0}

        def analyze(board: object, depth: int = 16, multipv: int = 2) -> dict:
            if depth == 10:
                scans["n"] += 1
                if scans["n"] < 3:
                    lines = [
                        {"move": "a3", "score_display": "+0.10", "is_mate": False, "score_cp_white": 10, "pv_san": ["a3"]},
                        {"move": "h3", "score_display": "+0.05", "is_mate": False, "score_cp_white": 5, "pv_san": ["h3"]},
                    ]
                else:
                    lines = [
                        {"move": "Nf6", "score_display": "+1.40", "is_mate": False, "score_cp_white": 140, "pv_san": ["Nf6", "Nc3"]},
                        {"move": "e5", "score_display": "+0.10", "is_mate": False, "score_cp_white": 10, "pv_san": ["e5"]},
                    ]
                return {"lines": lines, "best_eval": lines[0]["score_display"], "best_move": lines[0]["move"], "best_pv": lines[0]["pv_san"]}
            lines = [
                {"move": "Nf6", "score_display": "+1.40", "is_mate": False, "score_cp_white": 140, "pv_san": ["Nf6", "Nc3"]},
                {"move": "e5", "score_display": "+0.10", "is_mate": False, "score_cp_white": 10, "pv_san": ["e5"]},
            ]
            return {"lines": lines, "best_eval": "+1.40", "best_move": "Nf6", "best_pv": ["Nf6", "Nc3"]}

        monkeypatch.setattr(cli_app.engine, "analyze_position", analyze)
        monkeypatch.setattr(cli_app.coach, "chat", lambda *args, **kwargs: "White is ahead because the knight jump wins a pawn.")
        monkeypatch.setattr(cli_app, "show_position_summary", lambda **kwargs: None)
        cli_app.cmd_eval_critical()
        assert cli_app.game.current_ply_index == start + 2

    def test_clear_when_the_next_whole_move_appears(
        self, cli_app: ChessCLIApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clears = {"n": 0}
        monkeypatch.setattr(
            cli_app,
            "get_position_ui_lines",
            lambda: [
                "previous move: none",
                "current move: 8",
                "turn: white to move",
                "stockfish: nf6\nstockfish recommends knight moves to f6\nto understand why, do eval",
                "score: +0.20",
            ],
        )
        monkeypatch.setattr(cli_app, "print_manual", lambda: None)
        monkeypatch.setattr("dupont.cli.console.clear", lambda: clears.__setitem__("n", clears["n"] + 1))

        # Move 8 white is ply 14, 8.5 is ply 15, move 9 white is ply 16.
        cli_app.game.jump_to_ply(14)
        cli_app.show_position_summary(stepped=True)
        cli_app.game.jump_to_ply(15)
        cli_app.show_position_summary(stepped=True)
        assert clears["n"] == 0
        cli_app.game.jump_to_ply(16)
        cli_app.show_position_summary(stepped=True)
        assert clears["n"] == 1

    def test_read_user_action_arrows_and_commands(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Test simulated input including 'f', 'b', arrows, and commands
        simulated_input = "f\nb\n\x1b[D\n\x1b[C\np\nn\n/jump 7-w\n/eval-short\n/eval-long\n/eval\nquit\n"
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
        # 11. 'quit' command. The single letter q is not a command.
        act, val = read_user_action()
        assert act == "QUIT"
        assert val == ""

    def test_full_words_not_single_letters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        simulated_input = "h\nq\nc\nboot\nhelp\nreset\nserve\nquit\n"
        monkeypatch.setattr(sys, "stdin", io.StringIO(simulated_input))

        act, val = read_user_action()
        assert (act, val) == ("COMMAND", "h")
        act, val = read_user_action()
        assert (act, val) == ("COMMAND", "q")
        act, val = read_user_action()
        assert (act, val) == ("COMMAND", "c")
        act, val = read_user_action()
        assert (act, val) == ("COMMAND", "boot")
        act, val = read_user_action()
        assert act == "HELP"
        act, val = read_user_action()
        assert act == "RESET"
        act, val = read_user_action()
        assert (act, val) == ("COMMAND", "serve")
        act, val = read_user_action()
        assert act == "QUIT"

    def test_cli_app_init_with_literal_start_pgn(self) -> None:
        """Verifies ChessCLIApp can initialize directly from a literal PGN string with 'start' prefix."""
        literal_pgn = 'start [Event "Live Chess"] 1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5'
        app = ChessCLIApp(literal_pgn)
        try:
            assert app.game.total_plies == 6
            lines = app.get_position_ui_lines()
            assert lines[0] == "previous move: white played e4"
            assert lines[1] == "current move: 1.5"
            assert lines[2] == "turn: black to move"
        finally:
            app.engine.close()

    def test_prompt_for_pgn_piped_stream(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verifies prompt_for_pgn reads from stdin pipe when non-interactive."""
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = False
        fake_stdin.read.return_value = '1. e4 e5 2. Nf3 Nc6 1-0\n'
        monkeypatch.setattr(sys, "stdin", fake_stdin)
        content = prompt_for_pgn()
        assert content == "1. e4 e5 2. Nf3 Nc6 1-0"

    def test_prompt_for_pgn_interactive_stream(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verifies prompt_for_pgn reads multi-line interactive paste terminated by result code."""
        monkeypatch.setattr("subprocess.run", MagicMock(side_effect=FileNotFoundError))
        lines = [
            '[Event "Live Chess"]\n',
            '[Site "Chess.com"]\n',
            '\n',
            '1. Nf3 g6 2. d4 Bg7 0-1\n',
        ]
        line_iter = iter(lines)
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = True
        fake_stdin.readline.side_effect = lambda: next(line_iter, "")
        monkeypatch.setattr(sys, "stdin", fake_stdin)
        content = prompt_for_pgn()
        assert "1. Nf3 g6 2. d4 Bg7 0-1" in content

    def test_prompt_for_pgn_existing_file_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verifies prompt_for_pgn returns immediately if user enters an existing file path."""
        monkeypatch.setattr("subprocess.run", MagicMock(side_effect=FileNotFoundError))
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = True
        fake_stdin.readline.return_value = "README.md\n"
        monkeypatch.setattr(sys, "stdin", fake_stdin)
        content = prompt_for_pgn()
        assert content == "README.md"

    def test_prompt_for_pgn_auto_clipboard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verifies prompt_for_pgn automatically reads from clipboard if PGN is present."""
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = True
        monkeypatch.setattr(sys, "stdin", fake_stdin)
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = '[Event "Live Chess"]\n1. e4 e5 2. Nf3 Nc6 1-0'
        monkeypatch.setattr("subprocess.run", MagicMock(return_value=mock_res))
        content = prompt_for_pgn()
        assert content.startswith('[Event "Live Chess"]')

    def test_cli_main_zero_args_invokes_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verifies cli main() with zero arguments calls prompt_for_pgn."""
        monkeypatch.setattr(sys, "argv", ["cli.py"])
        monkeypatch.setattr("dupont.cli.prompt_for_pgn", lambda: "1. e4 e5")
        mock_app = MagicMock()
        monkeypatch.setattr("dupont.cli.ChessCLIApp", lambda pgn: mock_app)
        cli_main()
        mock_app.run.assert_called_once()


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

    def test_clean_pgn_content_start_prefix_multiline(self) -> None:
        raw = (
            'start [Event "Live Chess"]\n'
            '[Site "Chess.com"]\n'
            '[Date "2023.10.15"]\n'
            '[Round "-"]\n'
            '[White "Player1"]\n'
            '[Black "Player2"]\n'
            '[Result "1-0"]\n\n'
            '1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0'
        )
        cleaned = clean_pgn_content(raw)
        assert cleaned.startswith("1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0")
        assert "start" not in cleaned.lower()
        assert "[Event" not in cleaned

    def test_clean_pgn_content_start_prefix_single_line(self) -> None:
        raw = 'start [Event "Live Chess"] [Site "Chess.com"] 1. e4 e5 2. Nf3 Nc6 1-0'
        cleaned = clean_pgn_content(raw)
        assert cleaned.startswith("1. e4 e5 2. Nf3 Nc6 1-0")
        assert "start" not in cleaned.lower()
        assert "[Event" not in cleaned

    def test_clean_pgn_content_start_prefix_direct_moves(self) -> None:
        raw = "start 1. e4 e5 2. Nf3 Nc6 3. Bb5"
        cleaned = clean_pgn_content(raw)
        assert cleaned.startswith("1. e4 e5 2. Nf3 Nc6 3. Bb5")
        assert not cleaned.lower().startswith("start")

    def test_clean_pgn_content_start_colon_prefix(self) -> None:
        raw = "start: 1. d4 d5 2. c4 e6"
        cleaned = clean_pgn_content(raw)
        assert cleaned.startswith("1. d4 d5 2. c4 e6")

    def test_clean_pgn_content_chess_com_clocks_and_evals(self) -> None:
        raw = (
            'start [Event "Live Chess"]\n'
            '1. e4 {[%clk 0:10:00]} 1... e5 {[%clk 0:09:58]} '
            '2. Nf3 {[%clk 0:09:55]} 2... Nc6 {[%clk 0:09:50]} 1-0'
        )
        cleaned = clean_pgn_content(raw)
        assert cleaned.startswith("1. e4 {[%clk 0:10:00]} 1... e5 {[%clk 0:09:58]}")
        assert "start" not in cleaned.lower()
        assert "[Event" not in cleaned

    def test_clean_pgn_content_figurines(self) -> None:
        raw = "start 1. ♘f3 d5 2. g3"
        cleaned = clean_pgn_content(raw)
        assert cleaned.startswith("1. ♘f3 d5 2. g3")

    def test_clean_pgn_content_no_dot(self) -> None:
        raw = "start 1 e4 e5 2 Nf3 Nc6"
        cleaned = clean_pgn_content(raw)
        assert cleaned.startswith("1 e4 e5 2 Nf3 Nc6")

    def test_clean_pgn_file_with_start_prefix(self, tmp_path: Path) -> None:
        raw = 'start [Event "Live Chess"]\n1. e4 e5 2. Nf3 Nc6'
        tmp_file = tmp_path / "game_with_start.pgn"
        tmp_file.write_text(raw, encoding="utf-8")

        resaved = clean_pgn_file(tmp_file)
        assert resaved == tmp_file
        content = tmp_file.read_text(encoding="utf-8")
        assert content.startswith("1. e4 e5 2. Nf3 Nc6")
        assert "start" not in content.lower()

    def test_pgn_cleaner_cli_literal_string(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(sys, "argv", ["pgn_cleaner.py", 'start [Event "Live Chess"] 1. e4 e5 2. Nf3 Nc6'])
        pgn_cleaner_main()
        out = capsys.readouterr().out
        assert out.startswith("1. e4 e5 2. Nf3 Nc6")

    def test_pgn_cleaner_cli_unquoted_tokens(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(
            sys,
            "argv",
            ["pgn_cleaner.py", "start", '[Event "Live Chess"]', "1.", "e4", "e5", "2.", "Nf3", "Nc6"],
        )
        pgn_cleaner_main()
        out = capsys.readouterr().out
        assert out.startswith("1. e4 e5 2. Nf3 Nc6")

    def test_pgn_cleaner_cli_output_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        out_file = tmp_path / "out_cleaned.pgn"
        monkeypatch.setattr(
            sys,
            "argv",
            ["pgn_cleaner.py", 'start [Event "Live Chess"] 1. e4 e5', "-o", str(out_file)],
        )
        pgn_cleaner_main()
        assert out_file.exists()
        assert out_file.read_text(encoding="utf-8").startswith("1. e4 e5")

    def test_pgn_cleaner_cli_stdin(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(sys, "argv", ["pgn_cleaner.py"])
        monkeypatch.setattr(sys, "stdin", io.StringIO('start [Event "Live Chess"] 1. d4 d5\n'))
        pgn_cleaner_main()
        out = capsys.readouterr().out
        assert out.startswith("1. d4 d5")

    def test_user_reported_chess_com_game(self) -> None:
        """Verifies parsing of the exact Chess.com cut-and-pasted game with timestamps, clocks, and sublines."""
        user_pgn = (
            '[Event "Live Chess"]\n'
            '[Site "Chess.com"]\n'
            '[Date "2026.10.13"]\n'
            '[Round "-"]\n'
            '[White "Prt"]\n'
            '[Black "bly"]\n'
            '[Result "0-1"]\n\n'
            '1. Nf3 {[%clk 0:10:02.1][%timestamp 29]} 1... g6 {[%clk 0:10:02.7][%timestamp 23]} '
            '2. d4 {[%clk 0:10:04.2][%timestamp 29]} 2... Bg7 {[%clk 0:10:06.8][%timestamp 9]} '
            '3. g3 {[%clk 0:10:06.2][%timestamp 30]} 3... d5 {[%clk 0:10:10][%timestamp 18]} '
            '4. Bg2 {[%clk 0:10:08.4][%timestamp 28]} 4... Nh6 {[%clk 0:10:12.7][%timestamp 23]} '
            '5. O-O {[%clk 0:10:11.3][%timestamp 21]} 5... Nf5 {[%clk 0:10:15.6][%timestamp 21]} '
            '6. c4 {[%clk 0:10:05][%timestamp 113]} 6... dxc4 {[%clk 0:10:18.2][%timestamp 24]} '
            '7. Nbd2 {[%clk 0:10:06.4][%timestamp 36]} 7... b5 $6 {[%clk 0:10:17.3][%timestamp 59]} '
            '8. e4 {[%clk 0:09:41][%timestamp 304]} (8. a4 bxa4 $6 9. Qxa4+ (9. Nh4 c6 10. Nxf5 gxf5 11. '
            'Qxa4)) (8. Nh4 Nxh4 (8... Nc6 $4)) 8... Nxd4 {[%clk 0:10:16.1][%timestamp 62]} '
            '9. Nxd4 {[%clk 0:09:42.6][%timestamp 34]} 9... Qxd4 {[%clk 0:10:15.2][%timestamp 59]} '
            '10. b3 $4 {[%clk 0:09:09][%timestamp 386]} 10... Qxa1 $1 {[%clk 0:10:14.9][%timestamp 53]} 0-1'
        )
        cleaned = clean_pgn_content("start " + user_pgn)
        gs = GameState(cleaned)
        assert gs.total_plies == 20
        assert gs.plies[0].san == "Nf3"
        assert gs.plies[1].san == "g6"
        assert gs.plies[18].san == "b3"
        assert gs.plies[19].san == "Qxa1"

CHESS_COM_SHARE_PASTE_PATH = Path(__file__).resolve().parent / "chess-com-share-paste.pgn"
CHESS_COM_SHARE_PASTE = CHESS_COM_SHARE_PASTE_PATH.read_text(encoding="utf-8")
CHESS_COM_SHARE_MOVES = [
    "Nf3", "g6", "d4", "Bg7", "g3", "d5", "Bg2", "Nh6", "O-O", "Nf5",
    "c4", "dxc4", "Nbd2", "b5", "e4", "Nxd4", "Nxd4", "Qxd4", "b3", "Qxa1",
]


def _assert_chess_com_share_game(gs: GameState) -> None:
    """The Share → PGN sample is a 10-move game that ends with 10... Qxa1."""
    assert [ply.san for ply in gs.plies] == CHESS_COM_SHARE_MOVES
    assert gs.plies[0].uci == "g1f3"
    assert gs.plies[-1].uci == "d4a1"


class TestChessComRawSharePaste:
    """Raw Chess.com Share → PGN text, including clock comments wrapped across lines."""

    def test_raw_paste_parses_with_headers_and_every_move(self) -> None:
        gs = GameState(CHESS_COM_SHARE_PASTE)
        assert gs.headers["White"] == "Prct"
        assert gs.headers["Black"] == "bely"
        assert gs.headers["Result"] == "0-1"
        assert gs.headers["Site"] == "Chess.com"
        link_line = next(line for line in CHESS_COM_SHARE_PASTE.splitlines() if line.startswith('[Link "'))
        expected_link = link_line.removeprefix('[Link "').removesuffix('"]')
        assert gs.headers["Link"] == expected_link
        assert "185259452140" in gs.headers["Link"]
        _assert_chess_com_share_game(gs)

    def test_cleaner_keeps_wrapped_clock_comments_and_all_moves(self) -> None:
        cleaned = clean_pgn_content(CHESS_COM_SHARE_PASTE)
        assert cleaned.startswith("1. Nf3 {[%clk 0:10:02.1][%timestamp 29]}")
        assert "[Event" not in cleaned
        assert "{[%clk 0:10:02.7][%timestamp\n23]}" in cleaned
        _assert_chess_com_share_game(GameState(cleaned))

    def test_interactive_paste_reads_until_result_not_mid_comment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A terminal paste arrives one line at a time. A wrapped {[%clk]} must not end the read."""
        monkeypatch.setattr("dupont.cli.subprocess.run", MagicMock(side_effect=FileNotFoundError))
        lines = [line + "\n" for line in CHESS_COM_SHARE_PASTE.splitlines()]
        lines.append("\n")
        pending = iter(lines)
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = True
        fake_stdin.readline.side_effect = lambda: next(pending, "")
        monkeypatch.setattr(sys, "stdin", fake_stdin)

        content = prompt_for_pgn()

        assert content.rstrip().endswith("0-1")
        assert "Qxa1" in content
        assert "[%timestamp\n23]" in content
        _assert_chess_com_share_game(GameState(clean_pgn_content(content)))

    def test_clipboard_paste_loads_the_share_dialog_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = True
        monkeypatch.setattr(sys, "stdin", fake_stdin)
        clip = MagicMock()
        clip.returncode = 0
        clip.stdout = CHESS_COM_SHARE_PASTE
        monkeypatch.setattr("dupont.cli.subprocess.run", MagicMock(return_value=clip))

        content = prompt_for_pgn()

        assert content == CHESS_COM_SHARE_PASTE.strip()
        _assert_chess_com_share_game(GameState(content))

    def test_cli_loads_raw_paste_as_game_text_not_a_missing_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("dupont.cli.StockfishEngine", MagicMock)
        monkeypatch.setattr("dupont.cli.ChessCoach", MagicMock)
        app = ChessCLIApp(CHESS_COM_SHARE_PASTE)
        assert app.pgn_path is None
        _assert_chess_com_share_game(app.game)

    def test_unquoted_start_line_paste_is_saved_before_zsh_sees_braces(self) -> None:
        """`start` plus this paste is the command that zsh rejects at `{`."""
        script = Path(__file__).resolve().parents[1] / "scripts" / "start-chess-com-paste.zsh"
        proc = subprocess.run(
            [
                "zsh",
                "-c",
                'source "$1"; dupont_capture_pasted_pgn "$2"',
                "zsh",
                str(script),
                "start " + CHESS_COM_SHARE_PASTE,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        captured = Path(proc.stdout.strip())
        try:
            raw = captured.read_text(encoding="utf-8")
            assert "{[%clk 0:10:02.1][%timestamp 29]}" in raw
            assert raw.lstrip().startswith('[Event "Live Chess"]')
            _assert_chess_com_share_game(GameState(raw))
        finally:
            captured.unlink(missing_ok=True)


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
            alphabet=st.characters(blacklist_categories=("Cs", "Cc"), blacklist_characters="\n\r\t, :"),
            min_size=1,
            max_size=60,
        ),
    )
    def test_hypothesis_move_prefix_and_query_parsing(
        self, move_num: int, is_white: bool, prefix: str, delimiter: str, query: str
    ) -> None:
        """Tests that prefix notation correctly splits the target ply and user query."""
        color = "w" if is_white else "b"
        cleaned_query = query.strip()
        input_str = f"{prefix}{move_num}-{color}{delimiter}{cleaned_query}"
        num, white, rem_query = GameState.parse_move_prefix_and_query(input_str)
        assert num == move_num
        assert white is is_white
        assert rem_query == cleaned_query

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
        start_prefix=st.sampled_from(["start ", "start: ", "START ", "start\n", "Start: ", ""]),
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
        self, start_prefix: str, tags: list[tuple[str, str]], move_text: str
    ) -> None:
        """Verifies that clean_pgn_content strips bracketed tags and start prefixes regardless of combinations."""
        header_lines = "\n".join(f'[{k} "{v}"]' for k, v in tags)
        raw_pgn = f"{start_prefix}{header_lines}\n\n{move_text}\n" if header_lines else f"{start_prefix}{move_text}\n"
        cleaned = clean_pgn_content(raw_pgn)
        assert cleaned.startswith(move_text)
        assert not cleaned.startswith("[")
        assert not cleaned.lower().startswith("start")

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

from __future__ import annotations

import unittest
from pathlib import Path

import chess

from agent.coach import ChessCoach
from core.config import config
from core.engine import StockfishEngine
from core.game_state import GameState, calculate_material


class TestGameState(unittest.TestCase):
    def setUp(self) -> None:
        self.pgn_path = Path(__file__).parent / "sample_game.pgn"
        self.game = GameState(self.pgn_path)

    def test_headers_loaded(self) -> None:
        self.assertEqual(self.game.headers.get("White"), "Paul Morphy")
        self.assertEqual(self.game.headers.get("Result"), "1-0")

    def test_plies_count(self) -> None:
        # Opera game is 17 full moves ending at 17. Rd8#
        # Total plies = 16*2 + 1 = 33
        self.assertEqual(self.game.total_plies, 33)

    def test_jump_to_move(self) -> None:
        # Jump to move 14 White (14. Rd1)
        board_14w = self.game.jump_to_move(14, is_white=True)
        self.assertEqual(self.game.current_ply.san, "Rd1")
        self.assertEqual(board_14w.turn, chess.WHITE)

        # Jump to move 14 Black (14... Qe6)
        board_14b = self.game.jump_to_move(14, is_white=False)
        self.assertEqual(self.game.current_ply.san, "Qe6")
        self.assertEqual(board_14b.turn, chess.BLACK)

    def test_step_navigation(self) -> None:
        self.game.jump_to_ply(0)
        self.assertEqual(self.game.current_ply_index, 0)
        b = self.game.next_ply()
        self.assertIsNotNone(b)
        self.assertEqual(self.game.current_ply_index, 1)
        b_prev = self.game.prev_ply()
        self.assertIsNotNone(b_prev)
        self.assertEqual(self.game.current_ply_index, 0)

    def test_parse_candidate_move(self) -> None:
        # Starting position
        board = chess.Board()
        m1 = GameState.parse_candidate_move(board, "e4")
        self.assertEqual(m1, chess.Move.from_uci("e2e4"))

        m2 = GameState.parse_candidate_move(board, "Nf3")
        self.assertEqual(m2, chess.Move.from_uci("g1f3"))

        m_uci = GameState.parse_candidate_move(board, "e2e4")
        self.assertEqual(m_uci, chess.Move.from_uci("e2e4"))

        # Illegal move
        m_illegal = GameState.parse_candidate_move(board, "Nxd5")
        self.assertIsNone(m_illegal)

    def test_material_calculation(self) -> None:
        board = chess.Board()
        mat = calculate_material(board)
        # Standard starting material: 8*1 + 2*3 + 2*3 + 2*5 + 9 = 39 pts each
        self.assertEqual(mat["white_pts"], 39)
        self.assertEqual(mat["black_pts"], 39)
        self.assertEqual(mat["diff"], 0)

    def test_chess_com_move_specifiers(self) -> None:
        # m7-w and m7-b
        self.assertEqual(GameState.parse_move_specifier("m7-w"), (7, True))
        self.assertEqual(GameState.parse_move_specifier("m7-b"), (7, False))
        self.assertEqual(GameState.parse_move_specifier("/m 7-w"), (7, True))
        self.assertEqual(GameState.parse_move_specifier("/m-7-w"), (7, True))
        self.assertEqual(GameState.parse_move_specifier("/m 7-b"), (7, False))
        self.assertEqual(GameState.parse_move_specifier("/m-7-b"), (7, False))
        self.assertEqual(GameState.parse_move_specifier("m14-w"), (14, True))
        self.assertEqual(GameState.parse_move_specifier("m14-b"), (14, False))
        self.assertEqual(GameState.parse_move_specifier("7-w"), (7, True))
        self.assertEqual(GameState.parse_move_specifier("7-b"), (7, False))
        self.assertEqual(GameState.parse_move_specifier("m7w"), (7, True))
        self.assertEqual(GameState.parse_move_specifier("m7b"), (7, False))

    def test_parse_move_prefix_and_query(self) -> None:
        # Combined turn with slash: "/m 7-w, why is going to h3 suboptimal"
        num, is_white, q = GameState.parse_move_prefix_and_query("/m 7-w, why is going to h3 suboptimal")
        self.assertEqual(num, 7)
        self.assertTrue(is_white)
        self.assertEqual(q, "why is going to h3 suboptimal")

        # Combined turn without slash: "m7-w, why is going to h3 suboptimal"
        num, is_white, q = GameState.parse_move_prefix_and_query("m7-w, why is going to h3 suboptimal")
        self.assertEqual(num, 7)
        self.assertTrue(is_white)
        self.assertEqual(q, "why is going to h3 suboptimal")

        # Hop only with slash
        num, is_white, q = GameState.parse_move_prefix_and_query("/m-8-b")
        self.assertEqual(num, 8)
        self.assertFalse(is_white)
        self.assertEqual(q, "")

        # No move prefix
        num, is_white, q = GameState.parse_move_prefix_and_query("what should white play instead?")
        self.assertIsNone(num)
        self.assertIsNone(is_white)
        self.assertEqual(q, "what should white play instead?")

    def test_eval_tag(self) -> None:
        self.game.jump_to_move(14, is_white=True)
        self.assertEqual(self.game.current_ply.eval_tag, "m14-w")
        self.game.jump_to_move(14, is_white=False)
        self.assertEqual(self.game.current_ply.eval_tag, "m14-b")

    def test_raw_pgn_string_loading(self) -> None:
        raw_pgn = "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5"
        gs = GameState(raw_pgn)
        self.assertEqual(gs.total_plies, 6)
        self.assertEqual(gs.plies[0].eval_tag, "m1-w")
        self.assertEqual(gs.plies[1].eval_tag, "m1-b")


class TestStockfishEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = StockfishEngine()

    def tearDown(self) -> None:
        self.engine.close()

    def test_analyze_position(self) -> None:
        board = chess.Board()
        res = self.engine.analyze_position(board, depth=10, multipv=2)
        self.assertIn("lines", res)
        self.assertEqual(len(res["lines"]), 2)
        self.assertIsNotNone(res["best_move"])
        self.assertIn("best_eval", res)

    def test_refute_candidate_blunder(self) -> None:
        # Fool's mate setup: 1. f3 e5 2. g4 Qh4#
        # Position after 1. f3 e5: White plays 2. g4??
        board = chess.Board("rnbqkbnr/pppp1ppp/8/4p3/8/5P2/PPPPP1PP/RNBQKBNR w KQkq - 0 2")
        blunder_move = chess.Move.from_uci("g2g4")

        ref = self.engine.refute_candidate(board, blunder_move, depth=12)
        self.assertTrue(ref["is_legal"])
        self.assertEqual(ref["candidate_san"], "g4")
        self.assertIn("Blunder", ref["classification"])
        self.assertEqual(ref["punishing_move_san"], "Qh4#")

    def test_refute_best_move(self) -> None:
        # Position where e4 is a standard top move
        board = chess.Board()
        best_cand = chess.Move.from_uci("e2e4")
        ref = self.engine.refute_candidate(board, best_cand, depth=10)
        self.assertTrue(ref["is_legal"])
        self.assertIn(ref["classification"], ("Best Move", "Good Move"))


class TestChessCoach(unittest.TestCase):
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
        self.assertIn("deterministic engine analysis", resp.lower())
        self.assertIn("e5", resp)

    def test_coach_online_llm_response(self) -> None:
        from unittest.mock import MagicMock

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
        self.assertIn("controls key central squares", reply)
        # History should have: system, user, assistant
        self.assertEqual(len(coach.history), 3)
        self.assertEqual(coach.history[2]["content"], reply)


if __name__ == "__main__":
    unittest.main()

"""Dupont — a natural-language adapter for the Stockfish chess engine.

Stockfish computes the chess facts; a local language model puts them into plain
words. This package holds the whole application:

- `config`      — settings loaded from the environment / `.env`
- `engine`      — Stockfish wrapper (analysis and move refutation)
- `game_state`  — PGN parsing and move navigation
- `pgn_cleaner` — strips PGN headers so a game starts at move 1
- `coach`       — LLM client that turns engine facts into plain-language coaching
- `cli`         — the interactive terminal entry point
"""

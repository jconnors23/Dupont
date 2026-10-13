---
hide:
  - toc
icon: material/flag-checkered
---

# Status & Roadmap

Dupont is a personal-use prototype at its **v1** release. This page is honest about what works today, what it depends on, and what is planned next. It is not a product announcement. Everything before the v1 release is referred to as v0.

## Status Markers

The phases and tables below use three markers:

- ✅ **Done** — built and working now.
- 🟡 **In progress / next** — the current focus or the immediately planned work.
- ⬜ **Planned** — intended, but not started.

## Phases

### ✅ Phase 0 — Scaffolding

The groundwork: the full working skeleton of the tool and its documentation. Complete.

- ✅ One source package `dupont/`: move navigation (`game_state.py`), the Stockfish engine wrapper (`engine.py`), the coaching LLM client (`coach.py`), the PGN cleaner (`pgn_cleaner.py`), settings (`config.py`), and the CLI (`cli.py`).
- ✅ The anti-hallucination design: the coach only ever receives engine facts, never calculates chess itself.
- ✅ Offline fallback that prints engine facts when no language model is running.
- ✅ Documentation site (this set), themed, with the dual-engine design and a glossary, plus the GitHub Pages workflow.

### ✅ Phase 1 — Prototype testing, debugging, and the v1 interface (the v1 release)

The prototype was exercised on real games and the interactive interface was reworked around what that revealed. This is the **v1** release; everything before it was v0.

- ✅ Fixed loading a game copied straight from Chess.com. The failure was in the shell, not the parser: a zsh helper (`scripts/start-chess-com-paste.zsh`) now captures a pasted game before the clock-comment braces trip a shell parse error. Added clipboard and piped-input paths as reliable alternatives.
- ✅ Reworked the interactive view: the command list prints above the first position and then steps aside; the position summary shows the previous and current move, whose turn it is in words, the engine's best move named in plain language, and the score; the FEN moved out of the display into state; the screen clears as you cross into a new move number; everything is left-aligned with cyan banners and colored move notation.
- ✅ Settled the command surface on whole words (`serve`, `help`, `quit`, `reset`) with single letters reserved for stepping. Added `serve` (starts the local coach and waits until it is ready), `eval-score` (why the score is even or who is ahead), and `eval-critical` (skip to the next critical decision and explain it); `reset` jumps to the start of the game.
- ✅ Gave the coach the score, the plain verdict (even / ahead), and the material count as facts, and firmed up the offline fallback summary.
- ✅ Test suite grown to 68 tests (pytest, MagicMock, Hypothesis), including a dedicated class for parsing a raw Chess.com share-paste; added a `make pilot` interactive practice game that genuinely exercises the cleaner.

### ⬜ Phase 2 — Second engine (Leela Chess Zero)

Leela Chess Zero (Lc0) is a neural-network chess engine that learned to play from self-play rather than hand-written rules. It is strong at long-term positional judgement, which is where Stockfish's forcing-line search is less telling.

- ⬜ Add the Lc0 positional evaluator behind the shared evaluation layer, starting with the workstation GPU backend.
- ⬜ Feed Lc0's positional assessments into the coach's fact block alongside Stockfish's tactical data.

### ⬜ Phase 3 — Hardware-profile switching and polish

- ⬜ Make the hardware profile fully switchable by configuration, including the Lc0 backend, so the same checkout runs on both the workstation and the laptop without edits.
- ⬜ Tidy the setup toward a closer-to-one-command bootstrap once the engine layer settles.

## What Works Today

The core idea is working: **a natural-language adapter for Stockfish beats handing a PGN to a raw chatbot.** Stockfish produces every tactical fact, and the language model only puts those facts into words, which avoids the made-up moves and wrong evaluations a model produces when it reasons about a board on its own.

| Area | Status |
| :--- | :--- |
| PGN loading from a file, clipboard, pipe, or Chess.com paste | ✅ Working |
| Move navigation (step, jump, skip to next critical decision) | ✅ Working |
| Stockfish analysis, scoring, and refutations | ✅ Working |
| Evaluation commands (`eval`, `eval-long`, `eval-score`, `eval-critical`) | ✅ Working |
| Local language-model coaching through an OpenAI-compatible endpoint, started with `serve` | ✅ Working |
| Offline fallback that prints engine facts when no model is running | ✅ Working |
| Prototype tested and debugged on real games | ✅ Working (v1) |
| Second engine (Lc0) for positional judgement | ⬜ Planned (Phase 2) |
| Hardware-profile switching between workstation and laptop | 🟡 Partial — engine path and model endpoint are configurable; Lc0 backend selection is not built |

## What It Runs On

Dupont is local-first and single-machine. There is no hosted version and no multi-user support, by design. It is built around two personal hardware setups:

- A workstation with an NVIDIA RTX 5070 Ti, where Stockfish runs on the CPU and the heavier models and the planned Lc0 backend run on the GPU.
- An Apple Silicon MacBook Pro with 32 GB of unified memory, where everything runs on-device, with a remote model endpoint only as a fallback.

The full specifications and the reasoning behind them are on the [Dual-Engine Design](./architecture/design.md) page.

## Known Constraints

- **It is not a playing engine.** It reviews games that have already been played; it does not play against you.
- **Coaching quality depends on the local model.** A small model gives rougher advice than a large one, even though the underlying engine facts are identical. The model is bounded by whatever fits in local memory.
- **The move labels are fixed rules of thumb.** "Blunder," "Mistake," and the rest come from fixed centipawn cutoffs, not from a sense of the game's style or the players' level.
- **It explains, it does not grade you.** The tool tells you what happened in a position and why a move works or fails. It does not track progress or score overall play.
- **Not public-facing.** The documentation here is working notes, not a user manual, and the setup assumes you are comfortable with a terminal and a Python environment.

## Where To Start

New to the project? Read the [Overview](./index.md) first, then [Local Setup](./how-to-run.md) to get a session going, and keep the [Commands Reference](./using-the-coach.md) open while you explore.

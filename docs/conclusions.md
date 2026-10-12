---
hide:
  - toc
---

# Status & Roadmap

Dupont is an early prototype for personal use. This page is honest about what works today, what it depends on, and what is planned next. It is not a product announcement.

## Status Markers

The phases and tables below use three markers:

- ✅ **Done** — built and working now.
- 🟡 **In progress / next** — the current focus or the immediately planned work.
- ⬜ **Planned** — intended, but not started.

## Phases

### ✅ Phase 0 — Scaffolding (completed today)

The groundwork was built in a single session: the full working skeleton of the tool and its documentation. This phase is complete.

- ✅ Core modules: PGN loading and move navigation (`core/game_state.py`), the Stockfish engine wrapper (`core/engine.py`), the coach adapter (`agent/coach.py`), and settings (`core/config.py`).
- ✅ Interactive terminal REPL (`cli.py`) with slash commands: move hop, ask, refute, evaluate, step, board, reset, and quit.
- ✅ The anti-hallucination design: the coach only ever receives engine facts, never calculates chess itself.
- ✅ Offline fallback that prints engine facts when no language model is running.
- ✅ Test suite (15 tests, passing) covering navigation, move-address parsing, the engine wrapper, and the coach.
- ✅ Documentation site (this set), themed, with the dual-engine design and a glossary, plus the GitHub Pages workflow.

### 🟡 Phase 1 — Prototype testing and debugging (next)

The next phase is to actually exercise the prototype on real games and fix what breaks. This is the current focus.

- 🟡 Run real PGNs end to end (not just the sample) and confirm the coach's explanations hold up against the engine facts.
- 🟡 Debug edge cases in move parsing, navigation, and the slash-command surface.
- 🟡 Check behavior when the language model is slow, unreachable, or returns something unexpected.
- 🟡 Tighten the prompt and fact block where the coaching reads thin or drifts from the engine's numbers.
- ⬜ Note recurring problems and settle the command surface before building more on top of it.

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
| PGN loading and move navigation | ✅ Working |
| Stockfish analysis, scoring, and refutations | ✅ Working |
| Local language-model coaching through an OpenAI-compatible endpoint | ✅ Working |
| Offline fallback that prints engine facts when no model is running | ✅ Working |
| Prototype tested and debugged on real games | 🟡 Next (Phase 1) |
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

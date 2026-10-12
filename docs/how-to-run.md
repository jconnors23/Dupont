---
hide:
  - toc
---

# Local Setup

These are the setup notes for running Dupont on your own machine. It is a personal prototype, so this is a developer-oriented checklist rather than a polished install guide — there is no packaged release and no hosted version. This page is the one place that names the full environment you need.

## What You Need

| Requirement | Why | How to get it |
| :--- | :--- | :--- |
| Python 3.11 or newer | Runs the program. Developed and tested on Python 3.13. | python.org or a version manager like pyenv |
| Stockfish | The chess engine that does all the exact calculation. | `brew install stockfish` on macOS |
| A local language model | Does the plain-language explaining. The default settings expect Ollama. | ollama.com, then `ollama pull llama3.1:8b` |

The language model piece is optional for the engine features. If no model is running, the coach prints the engine's analysis directly instead of a written explanation, so move scores and refutations still work.

## Step 1: Install The Python Packages

The project pins its dependencies in `requirements.txt`. Install them into a virtual environment:

```bash
python -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

The installed packages are `python-chess` (board logic and PGN parsing), `openai` (the client used to talk to the local model), `python-dotenv` (reads the `.env` file), `rich` (the colored terminal display), and `pydantic`.

## Step 2: Point The Program At Your Tools

The program reads four settings from your environment or a `.env` file in the project root. Copy the example file and edit it if your paths differ:

```bash
cp .env.example .env
```

The settings and their defaults:

| Setting | Default | What it is |
| :--- | :--- | :--- |
| `STOCKFISH_PATH` | `/opt/homebrew/bin/stockfish` | Where the Stockfish binary lives. If Stockfish is on your PATH, the program finds it automatically. |
| `LLM_BASE_URL` | `http://localhost:11434/v1` | The address of your local model server. The default is Ollama's. |
| `LLM_MODEL` | `llama3.1:8b` | Which model to use for explanations. |
| `OPENAI_API_KEY` | `ollama` | A placeholder key. Ollama ignores it, but the client library requires some value. |

## Step 3: Start Your Local Model

If you are using Ollama, make sure it is running and the model is pulled:

```bash
ollama pull llama3.1:8b
```

```bash
ollama serve
```

Skip this step if you only want the engine analysis; the coach will fall back to showing engine facts.

## Step 4: Run A Game

Point the program at a PGN file. A sample game is included:

```bash
python -m dupont.cli tests/sample_game.pgn
```

That opens the interactive session on the first move. From there, type a command or a question. The [Commands Reference](./using-the-coach.md) page lists everything you can type.

## Running The Tests

The tests are written in `pytest`, using `unittest.mock.MagicMock` for isolating network calls and `hypothesis` for generative property-based testing. They cover game navigation, move-address parsing (including the `/jump 7-w` form and the hop-and-ask prefix), the engine wrapper (including finding a forced mate as a refutation), the coach's online and offline behavior, the PGN cleaner, and the CLI's position-summary formatting. The engine and `/eval` tests need Stockfish installed; the coaching tests use a local model when one is reachable and otherwise exercise the offline fallback.

```bash
pytest
```

Or run via the test runner script:

```bash
python run_tests.py
```

All 31 tests pass on a setup with Python 3.13 and Stockfish installed.

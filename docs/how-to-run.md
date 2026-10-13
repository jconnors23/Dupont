---
hide:
  - toc
icon: material/chess-pawn
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

## Step 3: Pull The Model (One Time)

If you are using Ollama, pull the default model once:

```bash
ollama pull llama3.1:8b
```

You do not have to start the server by hand. Inside a session, the `serve` command launches `ollama serve` for you and waits until it is ready. You can still start it manually with `ollama serve` if you prefer. Skip the model entirely if you only want the engine analysis; the coach falls back to printing engine facts when no model is running.

## Step 4: Run A Game

There are a few ways to hand a game to the program.

**From a PGN file.** Point it at the included sample:

```bash
python -m dupont.cli tests/sample_game.pgn
```

**From the clipboard or an interactive paste.** Run the launcher with no argument and it reads a game from your clipboard, or lets you paste one at the prompt:

```bash
./start
```

**Piped in.** Send a game straight through standard input:

```bash
pbpaste | ./start
```

The `make` targets wrap the same launcher: `make start` (clipboard or paste), `make start games/2.pgn` (a file), and `make pilot` (opens a built-in, deliberately messy practice game that exercises the PGN cleaner). To clean a game down to its moves without opening a session, use `make cleanup` (clipboard or prompt) or `make cleanup games/2.pgn`; add `OUT=clean.pgn` to write the result to a file.

Once a game is loaded, the session opens on the first move with the command list shown above the position. From there, type a command or a question. The [Commands Reference](./using-the-coach.md) page lists everything you can type.

!!! note "Pasting a game copied from Chess.com"
    A game copied with Chess.com's **Share → PGN** carries clock comments like `{[%clk 0:10:02][%timestamp 29]}`. Those curly braces are a problem for the shell, not for Dupont: in zsh, typing the word `start` followed by an unquoted paste that contains `{ }` fails with a shell parse error before the program ever runs. The repo ships a small zsh helper, `scripts/start-chess-com-paste.zsh`, that captures the pasted text safely before zsh chokes on the braces; a project setup can source it so a raw Chess.com paste just works. The reliable paths that always work are the clipboard (`./start`) and the pipe (`pbpaste | ./start`).

!!! note "A loaded PGN file is rewritten in place"
    When you load a game from a file, Dupont strips the header tags and anything above move 1 and rewrites that file, so it starts directly at `1. ...`. The sample file is cleaned to its movetext on first run. Keep an original copy if the headers matter to you.

## Running The Tests

The tests are written in `pytest`, using `unittest.mock.MagicMock` for isolating network calls and `hypothesis` for generative property-based testing. They cover game navigation, move-address parsing (including the `jump 7-w` form and the hop-and-ask prefix), the engine wrapper (including finding a forced mate as a refutation), the coach's online and offline behavior, the PGN cleaner, the CLI's position summary and commands, and parsing a raw game copied from Chess.com (clocks, timestamps, and the shell-safe paste). The engine tests need Stockfish installed; the coaching tests mock the model API, so they run offline without a model server.

```bash
pytest
```

Or run via the test runner script, which the `make test` target also calls:

```bash
python run_tests.py
```

The suite has 68 tests. They pass on a setup with Python 3.13 and Stockfish installed; the engine tests need Stockfish on your PATH.

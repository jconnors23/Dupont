# Dupont

[![Documentation](https://img.shields.io/badge/docs-GitHub%20Pages-7a74c4?logo=materialformkdocs&logoColor=white)](https://jconnors23.github.io/dupont/)

> A natural-language Stockfish adapter: ask about a chess game in plain English and get answers grounded in the engine, not hallucinated. Local prototype, individual use.

**Live documentation site: [jconnors23.github.io/dupont](https://jconnors23.github.io/dupont/)**

Dupont is a **natural-language adapter for Stockfish**. It reads a saved chess game (a PGN file) and lets you ask about it in plain English — "why was that a mistake?", "what was my opponent threatening?" — with every answer grounded in the engine's actual calculation rather than guessed at.

It exists to fix a specific failure: uploading a PGN straight into a general chatbot like ChatGPT or Gemini and asking about the game reliably produces **hallucinated game states** — the model misremembers where pieces are, invents moves, and gives confident but wrong evaluations. Dupont puts a real chess engine in the loop so that cannot happen.

The design keeps two jobs apart. **Stockfish** does the exact calculation (best moves, position scores, refutations). A **local language model** (through Ollama) only puts those facts into words; it is told to explain what the engine found and never to invent moves or evaluations of its own. The language model is a translator for the engine, not a chess player in its own right.

> **Status:** early prototype for personal, single-machine use. There is no packaged release and no hosted version; the docs are working notes rather than a public user guide.

## How It Works

```mermaid
%%{init: {'theme':'base','themeVariables':{'fontSize':'18px','primaryColor':'#7a74c4','primaryTextColor':'#f6f6fb','primaryBorderColor':'#b4afe8','lineColor':'#b4afe8'},'flowchart':{'nodeSpacing':55,'rankSpacing':65}}}%%
flowchart TB
    PGN[PGN game file] --> GS[Game navigation]
    GS -->|current position| ENG[Stockfish engine]
    ENG -->|scores, best moves,<br/>refutations| FACTS[Engine facts]
    USER[Your question] --> COACH[Language model coach]
    FACTS --> COACH
    COACH -->|plain-language answer| OUT[Terminal display]
    GS --> OUT
```

## Quickstart

Install Stockfish and the Python packages, then run the included sample game. The one-time setup:

```bash
brew install stockfish
```

```bash
python -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

Optionally start a local model for written explanations (skip it and the coach prints engine facts instead):

```bash
ollama pull llama3.1:8b
```

```bash
ollama serve
```

Run a game:

```bash
python cli.py tests/sample_game.pgn
```

Run the tests (uses Python's built-in `unittest`):

```bash
python -m unittest tests.test_chess_coach -v
```

This project targets Python 3.11+ (developed on 3.13). Full setup details are in the documentation linked below.

## Project Layout

```text
dupont/
├── cli.py                     # Interactive terminal loop: board, commands, questions
├── core/
│   ├── config.py              # Reads engine path and model settings from .env
│   ├── engine.py              # Stockfish wrapper: analysis and move refutation
│   └── game_state.py          # PGN parsing and move navigation
├── agent/
│   └── coach.py               # Sends engine facts + question to the language model
├── tests/
│   ├── test_chess_coach.py    # unittest suite (navigation, engine, coach)
│   └── sample_game.pgn        # The 1858 Opera Game
├── docs/                      # Documentation site source (MkDocs)
├── requirements.txt
└── .env.example               # Copy to .env and adjust paths
```

## Documentation

| Page | What it covers |
| :--- | :--- |
| [Overview](./docs/index.md) | What Dupont is and what it can do today |
| [How It Works](./docs/architecture.md) | The parts, how they talk, and why the coach cannot make up chess |
| [Dual-Engine Design](./docs/architecture/design.md) | Planned Stockfish + Lc0 layer and the target local hardware |
| [Local Setup](./docs/how-to-run.md) | Setting it up on your own machine |
| [Commands Reference](./docs/using-the-coach.md) | The interactive commands and output format |
| [Status & Roadmap](./docs/conclusions.md) | Prototype status, constraints, and what's planned |
| [Glossary](./docs/glossary.md) | Key terms, both chess and technical |

The full set is published as a site at **[jconnors23.github.io/dupont](https://jconnors23.github.io/dupont/)**. To browse it locally instead, run `mkdocs serve` and open the address it prints.

### Publishing The Site

The site deploys automatically to GitHub Pages on every push to `main`, via the workflow in `.github/workflows/docs.yml`. For the first deploy to work, enable Pages once in the repository: go to **Settings → Pages** and set the source to **GitHub Actions**. After that, each push rebuilds and republishes the site at the link above.

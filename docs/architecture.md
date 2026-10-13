---
hide:
  - toc
icon: material/chess-knight
---

# How It Works

Dupont is a natural-language adapter for Stockfish: the engine does the chess, and a language model only translates its output into words. The program is a single interactive terminal session built from a few small parts. Each part has one job, and they are kept apart on purpose so the exact chess calculation never gets mixed up with the plain-language translating.

## The Parts

| Part | File | What it does |
| :--- | :--- | :--- |
| Game navigation | `dupont/game_state.py` | Reads the PGN, splits it into individual half-moves, and tracks where you are in the game. |
| Chess engine | `dupont/engine.py` | Wraps Stockfish. Scores positions, lists top moves, and works out why a move fails. |
| Coach | `dupont/coach.py` | Sends the engine's facts and your question to the language model and returns its reply. |
| Terminal app | `dupont/cli.py` | The command loop you type into. Draws the position, reads your commands, starts the coach on request, and calls the other parts. |
| PGN cleaner | `dupont/pgn_cleaner.py` | Strips header tags so a loaded game starts at move 1. |
| Settings | `dupont/config.py` | Reads the engine path and model settings from your environment or a `.env` file. |
| Paste helper | `scripts/start-chess-com-paste.zsh` | A zsh helper that lets you paste a Chess.com game (with its clock comments) at the shell without the braces tripping a shell parse error. |

A half-move (one side playing once) is called a *ply*. A full move number like "14" covers White's 14th move and Black's reply, so the program tracks position by ply and lets you ask for either side of a move number.

## How A Question Becomes An Answer

When you ask the coach something, the position is analyzed first and the engine's results are handed to the language model. The model never calculates chess itself; it only rewrites the engine's findings as advice.

```mermaid
%%{init: {'theme':'base','themeVariables':{'fontSize':'20px','primaryColor':'#7a74c4','primaryTextColor':'#f6f6fb','primaryBorderColor':'#b4afe8','lineColor':'#b4afe8'},'flowchart':{'nodeSpacing':55,'rankSpacing':60}}}%%
flowchart TB
    A([You type a question]) --> B[Stockfish analyzes<br/>the current position]
    B --> C{Did you name<br/>a move?}
    C -->|yes| D[Stockfish also works out<br/>why that move fails]
    C -->|no| E[Use the position's<br/>best move and score]
    D --> F[Hand the engine facts<br/>to the model]
    E --> F
    F --> G([Read the plain-English answer])
```

If the question names a specific move, the app also asks the engine to refute that exact move. If it does not, but you are sitting on a move that was played in the game, the app refutes the played move so questions like "why is this a mistake?" have something concrete to explain.

## What The Engine Produces

!!! important "Every evaluation is computed by Stockfish, never by the language model"
    The scores, the best move, the candidate lines, the principal variations, the refutations, and the move-quality labels are all produced **programmatically by the Stockfish engine** — a real Stockfish process doing its own search and evaluation, with the results read back and formatted in plain Python. **No language model is involved in any of it.** There is no model call anywhere in the evaluation path: the number `+1.25`, the move `Nf6`, the label "Blunder" are all deterministic engine output. The language model is called **only afterward**, and **only** to put those already-computed facts into words — it never calculates a score, picks a move, or decides a label. If the model is turned off entirely, every evaluation above is unchanged; you simply get the engine facts without the prose.

The engine wrapper (`dupont/engine.py`) exposes two things the rest of the program relies on.

**Position analysis** returns the top candidate moves, each with a score from White's point of view, and the line of play the engine expects to follow. The wrapper can return several lines; the `/eval` command asks for the top two. Scores are shown in pawns (for example `+1.25` means White is ahead by a little over a pawn) or as a forced mate (for example `#+3` means mate in three for the side to move).

**Move refutation** takes one candidate move, plays it on a copy of the board, and asks the engine what the best reply is. It compares the position's value before and after, then labels the move. The labels come straight from how much the move loses, measured in centipawns (hundredths of a pawn):

| Label | How much the move loses (from the mover's side) |
| :--- | :--- |
| Best Move | Matches the engine's top choice, or loses nothing. |
| Good Move | Loses less than 0.30 of a pawn. |
| Inaccuracy | Loses 0.30 to 0.80 of a pawn. |
| Mistake | Loses 0.80 to 2.00 pawns. |
| Blunder | Loses 2.00 pawns or more, or walks into a forced mate. |

These thresholds are fixed in the engine wrapper, so the same move always gets the same label.

## Why The Coach Cannot Make Up Chess

The coach is given a strict instruction set and a block of engine facts, and nothing else to work from. The facts block names the position, whose turn it is, the move played, the engine's best move and score, the move being asked about and its label, and the opponent's punishing reply when there is one.

```mermaid
%%{init: {'theme':'base','themeVariables':{'fontSize':'20px','primaryColor':'#7a74c4','primaryTextColor':'#f6f6fb','primaryBorderColor':'#b4afe8','lineColor':'#b4afe8'},'flowchart':{'nodeSpacing':50,'rankSpacing':60}}}%%
flowchart LR
    A[Engine facts<br/>+ your question] --> B{Is the model<br/>running?}
    B -->|yes| C[Model explains the<br/>facts in plain English]
    B -->|no| D[Print the engine<br/>facts as they are]
```

The model is handed one thing — the engine's facts plus your question — and told to explain, never to calculate. Its instructions ask it to translate the engine's lines into human ideas (naming tactics like forks, pins, and back-rank weaknesses, or positional points like king safety and piece activity) and never to invent a move or a score. Because that is all it ever sees, it has nothing to hallucinate from.

If the language model server is unreachable, the coach does not fail. It falls back to printing the engine's facts in a readable form, so you still get the best move, the score, and the refutation even with no model running.

## Where State Lives

The game is loaded once into memory as a list of plies, and a single index marks the current position. Stepping forward or back, jumping to a move number, or skipping to the next critical decision just moves that index. The engine runs as a separate Stockfish process that the app starts on launch and shuts down on exit. The language model is a separate server; it does not start with the app, so the `serve` command launches it on demand and waits until it is ready. The coach keeps a running conversation history so follow-up questions have context, and resetting jumps back to the start of the game.

```mermaid
%%{init: {'theme':'base','themeVariables':{'fontSize':'20px','primaryColor':'#7a74c4','primaryTextColor':'#f6f6fb','primaryBorderColor':'#b4afe8','lineColor':'#b4afe8'},'flowchart':{'nodeSpacing':55,'rankSpacing':60}}}%%
flowchart TB
    A([Start with a game]) --> B[Load the game,<br/>start Stockfish]
    B --> C[Sit on a position]
    C -->|step, jump, eval, ask, serve| C
    C -->|quit| D([Close Stockfish and exit])
```

Each command just acts on the position you are sitting on, then hands you back to the same prompt — until you quit.

For the exact commands that drive these transitions, see the [Commands Reference](./using-the-coach.md).

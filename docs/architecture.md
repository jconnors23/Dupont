---
hide:
  - toc
---

# How It Works

Dupont is a natural-language adapter for Stockfish: the engine does the chess, and a language model only translates its output into words. The program is a single interactive terminal session built from four parts. Each part has one job, and they are kept apart on purpose so the exact chess calculation never gets mixed up with the plain-language translating.

## The Four Parts

| Part | File | What it does |
| :--- | :--- | :--- |
| Game navigation | `core/game_state.py` | Reads the PGN, splits it into individual half-moves, and tracks where you are in the game. |
| Chess engine | `core/engine.py` | Wraps Stockfish. Scores positions, lists top moves, and works out why a move fails. |
| Coach | `agent/coach.py` | Sends the engine's facts and your question to the language model and returns its reply. |
| Terminal app | `cli.py` | The command loop you type into. Draws the board, reads your commands, and calls the other three. |
| Settings | `core/config.py` | Reads the engine path and model settings from your environment or a `.env` file. |

A half-move (one side playing once) is called a *ply*. A full move number like "14" covers White's 14th move and Black's reply, so the program tracks position by ply and lets you ask for either side of a move number.

## How A Question Becomes An Answer

When you ask the coach something, the position is analyzed first and the engine's results are handed to the language model. The model never calculates chess itself; it only rewrites the engine's findings as advice.

```mermaid
%%{init: {'theme':'base','themeVariables':{'fontSize':'18px','primaryColor':'#7a74c4','primaryTextColor':'#f6f6fb','primaryBorderColor':'#b4afe8','lineColor':'#b4afe8','actorBkg':'#7a74c4','actorBorder':'#b4afe8','actorTextColor':'#f6f6fb','signalColor':'#d6d2f0','signalTextColor':'#d6d2f0','noteBkgColor':'#8b84e4','noteTextColor':'#15131f'}}}%%
sequenceDiagram
    participant You
    participant App as Terminal app (cli.py)
    participant Game as Game navigation
    participant Engine as Stockfish
    participant Coach as Language model

    You->>App: type a question
    App->>Game: what is the current position?
    Game-->>App: board + which move was played
    App->>Engine: analyze this position
    Engine-->>App: top moves, scores, best line
    App->>Engine: if a move was named, why does it fail?
    Engine-->>App: refutation and eval change
    App->>Coach: question + engine facts
    Coach-->>App: plain-language answer
    App-->>You: show the answer
```

If the question names a specific move, the app also asks the engine to refute that exact move. If it does not, but you are sitting on a move that was played in the game, the app refutes the played move so questions like "why is this a mistake?" have something concrete to explain.

## What The Engine Produces

The engine wrapper (`core/engine.py`) exposes two things the rest of the program relies on.

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
%%{init: {'theme':'base','themeVariables':{'fontSize':'20px','primaryColor':'#7a74c4','primaryTextColor':'#f6f6fb','primaryBorderColor':'#b4afe8','lineColor':'#b4afe8'},'flowchart':{'nodeSpacing':60,'rankSpacing':70,'padding':14}}}%%
flowchart TB
    SP[Fixed coaching instructions:<br/>explain, do not calculate] --> MSG
    EF[Engine facts for this position] --> FMT[Formatted facts block]
    Q[Your question] --> MSG[Message sent to the model]
    FMT --> MSG
    MSG --> LLM[Local language model via Ollama]
    LLM --> R{Did the model reply?}
    R -->|yes| ANS[Coaching answer in plain language]
    R -->|no, server down| FB[Fallback: show the engine facts directly]

    classDef engine fill:#7a74c4,stroke:#b4afe8,color:#f6f6fb,font-size:18px;
    classDef model fill:#2d2846,stroke:#b4afe8,color:#eceaf6,font-size:18px;
    classDef out fill:#8b84e4,stroke:#15131f,color:#15131f,font-size:18px;
    class EF,FMT engine;
    class SP,MSG,LLM model;
    class ANS,FB out;
```

The instructions tell the model to translate the engine's lines into human ideas (naming tactics like forks, pins, and back-rank weaknesses, or positional points like king safety and piece activity) and to never invent moves or scores. Because the model only sees the engine's facts, it has nothing to hallucinate from.

If the language model server is unreachable, the coach does not fail. It falls back to printing the engine's facts in a readable form, so you still get the best move, the score, and the refutation even with no model running.

## Where State Lives

The game is loaded once into memory as a list of plies, and a single index marks the current position. Stepping forward or back, or jumping to a move number, just moves that index. The engine runs as a separate Stockfish process that the app starts on launch and shuts down on exit. The coach keeps a running conversation history so follow-up questions have context, and you can clear that history at any time.

```mermaid
%%{init: {'theme':'base','themeVariables':{'fontSize':'20px','primaryColor':'#7a74c4','primaryTextColor':'#f6f6fb','primaryBorderColor':'#b4afe8','lineColor':'#b4afe8'},'state':{'nodeSpacing':60,'rankSpacing':70}}}%%
stateDiagram-v2
    [*] --> Loading: start with a PGN path
    Loading --> AtPosition: game parsed, engine started
    AtPosition --> AtPosition: step, jump, eval, ask, why-not
    AtPosition --> Exit: quit
    Exit --> [*]: engine process closed
```

For the exact commands that drive these transitions, see the [Commands Reference](./using-the-coach.md).

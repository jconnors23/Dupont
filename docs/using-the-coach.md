---
hide:
  - toc
icon: material/chess-rook
---

# Commands Reference

A reference for the interactive loop, kept as working notes for personal use. Once a game is loaded, each line you type is either a navigation key, a named command, or a plain-language question. This page lists what you can type and how to read what comes back.

Two kinds of input drive a session. **Single keypresses** (`f` and `b`, or the arrow keys) step through the game instantly, with no Enter. **Named commands and typed questions** do everything else: start the coach, evaluate a position, jump to the next critical moment, ask a question, and quit. Commands are whole words — `serve`, `help`, `quit`, `reset` — so that single letters stay free for stepping.

## Stepping Through The Game

The fastest way to move is one key at a time, with no Enter:

| Key | What it does |
| :--- | :--- |
| `f` or `→` | Step forward to the next move. |
| `b` or `←` | Step backward to the previous move. |

The up and down arrows also work (up steps back, down steps forward). These keys act the moment you press them, as long as you have not started typing a command. If you begin typing a word, the keys become normal text until you press Enter or clear the line.

When input is piped in rather than typed at a terminal (for tests, the `make pilot` target, or scripts), the same steps are available as typed words: `f` / `forward` / `n` / `next` to go forward, `b` / `back` / `p` / `prev` to go back.

!!! note "The screen clears as you cross into a new move"
    A whole move and its two halves stay on screen together. White's 8th and Black's 8th (shown as `8` and `8.5`) sit side by side; stepping forward into move 9 clears the screen first, so the view never piles up as you read through a game.

## The Command List

When a session opens, the command list is printed first, above the position. On later moves it steps out of the way and only the position shows; type `help` to bring the list back.

| Command | What it does |
| :--- | :--- |
| `serve` | Start the local coach (`ollama serve`) and wait until it is ready to answer. |
| `f` | Step forward one move (same as the `f` key). |
| `b` | Step back one move (same as the `b` key). |
| `eval` | Short coach notes on the top moves — the engine's top two moves, each with a one- or two-sentence explanation. |
| `eval-long` | A longer, full-paragraph explanation of the single top move. |
| `eval-score` | Explain why the current score is even, or why one side is ahead. |
| `eval-critical` | Jump forward to the next critical decision and explain who is winning and what the real options are. |
| `reset` | Jump back to the start of the game. |
| `help` | Show the command list again. |
| `quit` | Clear the screen and exit. |

A few extra inputs are accepted but kept off the printed list to avoid clutter:

| Also accepted | What it does |
| :--- | :--- |
| `clear` or `c` | Clear the screen without leaving the session. |
| `eval-short` | Show the top two moves with scores and continuation lines only — no coach text. (The top move already appears on every position, so this is rarely needed.) |
| `jump 7-w`, `7-w`, `7`, `/jump 7-w` | Jump to a move by number and color. See Move Addressing below. |
| `jump 7-w, <question>` | Jump and ask in one line, e.g. `jump 7-w, why is h3 bad?`. |
| `/q <question>`, `/ask <question>` | Ask the coach. Typing the question with no prefix does the same thing. |

Most commands also accept a leading slash (`/eval`, `/serve`, `/quit`, and so on) if that is your habit.

## Starting The Coach With `serve`

The written explanations come from a local language model served by Ollama. If it is not already running, type `serve`: it launches `ollama serve` in the background and waits until the server is accepting connections (up to about 20 seconds), then returns you to the prompt. If the server is already up, `serve` says so immediately. If Ollama is not installed, it tells you that instead. Everything except the written explanations works without ever running `serve`.

## Move Addressing

Positions are addressed the same way an online game review labels them: a move number with a color suffix. `jump 7-w` is White's 7th move, `jump 8-b` is Black's 8th. On startup the session opens on the first move.

The parser is forgiving about punctuation and spacing. All of these reach White's 7th move: `jump 7-w`, `/jump 7-w`, `7-w`, `7w`, `7`. Leaving the color off defaults to White. Legacy `/m 7-w` is also accepted.

## Asking A Question

Type a question in plain English and the coach answers, grounded in the engine's analysis of the current position. No prefix is needed; `/q <question>` and `/ask <question>` do the same thing.

If your question names a legal move, the coach grounds its answer in the engine's refutation of that exact move. For example, `why not exd5?` or `is c6d5 bad here?`: the program finds the move in your question, has Stockfish calculate the punishing reply, and feeds that refutation to the coach. If you ask about the position without naming a move (such as "why is this a mistake?") while sitting on a move that was actually played, the coach refutes the played move instead.

You can name a move in two ways. Standard notation like `Nxd5` (the common way games are written) works, and so does the plain from-square-to-square form like `c6d5`. The program is forgiving about small things: a lowercase piece letter, a trailing `!` or `?`, or castling written as `0-0` instead of `O-O`.

## Reading The Position Summary

Every time you move to a new position, the program prints a compact table. The exact position in machine form (its FEN) is tracked internally but not shown, to keep the view readable.

```text
previous move   white played nf3
current move    2.5
turn            black to move
stockfish       d6
                stockfish recommends pawn moves to d6
                to understand why, do eval
score           +0.42
```

Line by line:

- **previous move** — the half-move just played to reach this position (e.g. `white played nf3`).
- **current move** — the move number to play now. It reads as a whole number on White's turn (`2`) and a half-step on Black's turn (`2.5`), so you always know whose move it is at a glance.
- **turn** — whose move it is, in words: `white to move` or `black to move`.
- **stockfish** — the engine's single best move for the side to move (shown in gold), followed by a plain-language description of that move and a nudge to type `eval` for the reasoning.
- **score** — the engine's score for the position (see below for how to read it).

## Reading The Scores

Scores are always shown from White's point of view, so the same number means the same thing no matter whose turn it is.

- A positive number means White is better; a negative number means Black is better. The size is in pawns, so `+1.25` is a small edge for White and `-3.00` is a serious one for Black.
- A score from `-0.50` to `+0.50` is treated as even. That is the band `eval-score` and `eval-critical` call "even."
- A score written with `#` is a forced checkmate. `#+3` means the side to move can force mate in three; a negative mate score means the side to move is getting mated.

## The Three Depths Of Explanation

The engine's best move and score already appear on every position. The `eval` commands add written explanation on top, in increasing depth:

- **`eval`** — the top two moves, each with a one- or two-sentence note on why it is suggested.
- **`eval-long`** — a single full paragraph on the top move: the tactics, the plan, the piece activity, and the longer-term point.
- **`eval-score`** — a short paragraph on the score itself: why the position is even, or why one side is ahead, in terms of material, king safety, pawn structure, and activity.
- **`eval-critical`** — scans forward for the next moment where one move is clearly better than the alternative (a gap of at least a pawn between the top two engine lines, or a forced mate), jumps there, and explains who is winning and what each side's real options are. If no such moment remains, it says so and stays put.

## A Worked Example

The included sample is the 1858 "Opera Game" by Paul Morphy, a short, famous attacking game that ends in checkmate on move 17. It parses to **33 half-moves**. Step through it with `f` and `b` (or the arrow keys), jump straight to a point with `jump 7-w` or `jump 8-b`, type `eval` to see the engine's top moves with explanations, run `eval-critical` to skip to the sharpest moment, or ask in one line with `jump 10-w, why is this a good move?`. It is a good game to learn the commands on because the finish is forced and easy to follow.

```bash
python -m dupont.cli tests/sample_game.pgn
```

There is also a deliberately messy practice game that exercises the PGN cleaner, run with `make pilot`.

!!! note "A loaded PGN file is rewritten in place"
    When a game is loaded from a file, Dupont strips the header tags and anything above move 1 and **rewrites the file**, so it starts directly at `1. ...`. This keeps parsing simple but it does modify your file. Keep an original copy if the headers matter to you. The reasoning is on the [Design Rationale](./design-rationale.md) page.

For the setup this assumes, including how to paste a game straight from Chess.com, see [Local Setup](./how-to-run.md).

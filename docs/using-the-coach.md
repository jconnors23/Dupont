---
hide:
  - toc
---

# Commands Reference

A reference for the interactive loop, kept as working notes for personal use. Once a game is loaded, each line you type is either a navigation command, an analysis command, or a plain-language question. This page lists what you can type and how to read what comes back.

Two kinds of input drive a session. **Single keypresses** step through the game instantly — no Enter needed. **Slash commands** (and typed questions) do everything else: jump to a move, evaluate, refute, ask, and quit.

## Stepping Through The Game

The fastest way to move is one key at a time, with no Enter:

| Key | What it does |
| :--- | :--- |
| `f` or `→` | Step forward to the next move. |
| `b` or `←` | Step backward to the previous move. |

The up and down arrows also work (up steps back, down steps forward). These keys act the moment you press them, as long as you have not started typing a command. If you begin typing (a slash command or a question), the keys become normal text until you press Enter or clear the line.

When input is piped in rather than typed at a terminal (for tests or scripts), the same steps are available as typed words: `f` / `forward` / `n` / `next` to go forward, `b` / `back` / `p` / `prev` to go back.

## Move Addressing

Positions are addressed the same way an online game review labels them: a move number with a color suffix. `/jump 7-w` is White's 7th move, `/jump 8-b` is Black's 8th. On startup the session opens on the first move.

The parser is forgiving about the exact punctuation and spacing. All of these reach White's 7th move: `/jump 7-w`, `jump 7-w`, `7-w`, `7w`, `7`. Leaving the color off defaults to White. Legacy `/m 7-w` is also supported as an alias.

## Command Reference

| What you type | What it does |
| :--- | :--- |
| `/jump 7-w`, `/jump 8-b` | Jump to a move. `/jump 7-w` is White's 7th, `/jump 8-b` is Black's 8th. |
| `/jump 7-w, <question>` | Jump and ask in one line. Example: `/jump 7-w, why is h3 bad?`. A comma or colon between the two is optional. |
| `/eval-short` | Show Stockfish's top two candidate moves for the current position with scores and continuation lines. |
| `/eval` | Show top engine lines accompanied by a concise Ollama explanation of why each move is suggested at this time. |
| `/eval-long` | Send ONLY the top engine move to Ollama for an in-depth paragraph explanation of the decision. |
| `/w <move>`, `/why <move>` | Take a legal move you name and show why it fails, then explain it. Accepts `/w e5` or `/w c6d5`; `why not e5` also works. |
| `/q <question>`, `/ask <question>` | Ask the coach about the current position. You can also just type the question with no prefix. |
| `/n`, `/next` (or `f`) | Step forward one half-move — the typed form of the `f` key. |
| `/p`, `/prev` (or `b`) | Step backward one half-move — the typed form of the `b` key. |
| `/board`, `/b` | Draw the current position as a colored 2D board, with the last move's squares highlighted. |
| `/reset` | Clear the coach's conversation history and start fresh. |
| `/help`, `/h`, `?` | Show the quick manual again. |
| `/q`, `/quit`, `/exit` | Leave and shut down the engine process. |

!!! note "`/q` does two things"
    `/q` on its own quits the session. `/q` *followed by a question* asks the coach. So `/q` exits, while `/q why is this a mistake?` asks. If you just want to ask, typing the question with no prefix is the clearest option.

The startup banner leads with the `f` / `b` navigation keys, then lists the review commands — jump (`/jump`), ask (`/q`), evaluate (`/eval-short`, `/eval`, `/eval-long`), and quit (`/q`). The reset and help commands above are also available at any time.

You can name a move in two ways. Standard notation like `Nxd5` (the common way games are written) works, and so does the plain from-square-to-square form like `c6d5`. The program is forgiving about small things: a lowercase piece letter, a trailing `!` or `?`, or castling written as `0-0` instead of `O-O`.

## Reading The Position Summary

Every time you move to a new position, the program prints a compact five-line summary:

```text
current move: move 2-b to go
previous move: white played nf3
Top Engine Suggestion: d6
Current Eval Score: +0.42
FEN: rnbqkb1r/pppppppp/5n2/8/8/5N2/PPPPPPPP/RNBQKB1R b KQkq - 2 2
```

Line by line:

- **Current Move** — which move and player is to move now (e.g. `move 2-b to go`).
- **Previous Move** — the half-move that was just played to reach this position (e.g. `white played nf3` or `black played nc6`).
- **Top Engine Suggestion** — Stockfish's single best move for the side to move.
- **Current Eval Score** — the engine's score for the position (see below for how to read it).
- **FEN** — the position written as one line of text, the standard way to describe a single chess position.

## Reading The Scores

Scores are always shown from White's point of view, so the same number means the same thing no matter whose turn it is.

- A positive number means White is better; a negative number means Black is better. The size is in pawns, so `+1.25` is a small edge for White and `-3.00` is a serious one for Black.
- A score written with `#` is a forced checkmate. `#+3` means the side to move can force mate in three; a negative mate score means the side to move is getting mated.

## A Worked Example

The included sample is the 1858 "Opera Game" by Paul Morphy, a short, famous attacking game that ends in checkmate on move 17. It parses to **33 half-moves**. Step through it with `f` and `b` (or the arrow keys), jump straight to a point with `/jump 7-w` or `/jump 8-b`, type `/eval` to see the engine's top moves with explanations, or ask in one line with `/jump 10-w, why is this a good move?`. It is a good game to learn the commands on because the finish is forced and easy to follow.

```bash
python -m dupont.cli tests/sample_game.pgn
```

!!! note "The PGN is cleaned in place on load"
    When a game is loaded, Dupont strips the header tags and anything above move 1 and **rewrites the file**, so it starts directly at `1. ...`. This keeps parsing simple but it does modify your file. Keep an original copy if the headers matter to you. The reasoning is on the [Design Rationale](./design-rationale.md) page.

For the setup this assumes, see [Local Setup](./how-to-run.md).

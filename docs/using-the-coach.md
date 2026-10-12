---
hide:
  - toc
---

# Commands Reference

A reference for the interactive loop, kept as working notes for personal use. Once a game is loaded, each line you type is either a navigation command, an analysis command, or a plain-language question. This page lists what you can type and how to read what comes back.

Commands are written as slash commands (`/m`, `/eval`, `/w`, and so on). Most have short plain-word aliases too, so older habits like `eval` or `board` still work.

## Move Addressing

Positions are addressed the same way an online game review labels them: a move number with a color suffix. `/m 7-w` is White's 7th move, `/m 8-b` is Black's 8th. The prompt itself shows where you are, for example `[m7-w] >`.

The parser is forgiving about the exact punctuation and spacing. All of these reach White's 7th move: `/m 7-w`, `m7-w`, `m7w`, `m 7`, `7-w`, `7w`, `7`. Leaving the color off defaults to White. The leading `/m` (or `m`, or the word `move`) is optional when a bare number is unambiguous.

## Command Reference

| What you type | What it does |
| :--- | :--- |
| `/m 7-w`, `/m 8-b` | Jump to a move. `/m 7-w` is White's 7th, `/m 8-b` is Black's 8th. |
| `/m 7-w, <question>` | Jump and ask in one line. Example: `/m 7-w, why is h3 bad?`. A comma or colon between the two is optional. |
| `/q <question>`, `/ask <question>` | Ask the coach about the current position. You can also just type the question with no prefix. |
| `/w <move>`, `/why <move>` | Take a legal move you name and show why it fails, then explain it in plain language. Accepts `/w e5` or `/w c6d5`. `why not e5` also works. |
| `/eval`, `/e` | Show Stockfish's top two candidate moves for the current position, with scores and expected lines. |
| `/n`, `/next` | Step forward one half-move. |
| `/p`, `/prev` | Step backward one half-move. |
| `/board`, `/b` | Draw the current position as a colored board, with the last move's squares highlighted. |
| `/reset` | Clear the coach's conversation history and start fresh. |
| `/help`, `/h`, `?` | Show the quick manual again. |
| `/q`, `/quit`, `/exit` | Leave and shut down the engine process. |

!!! note "`/q` does two things"
    `/q` on its own quits the session. `/q` *followed by a question* asks the coach. So `/q` exits, while `/q why is this a mistake?` asks. If you just want to ask, typing the question with no prefix is the clearest option.

The startup banner lists five core commands — hop (`/m`), ask (`/q`), refute (`/w`), evaluate (`/eval`), and quit (`/q`) — because those carry a review session. The stepping, board, reset, and help commands above are also available at any time.

You can name a move in two ways. Standard notation like `Nxd5` (the common way games are written) works, and so does the plain from-square-to-square form like `c6d5`. The program is forgiving about small things: a lowercase piece letter, a trailing `!` or `?`, or castling written as `0-0` instead of `O-O`.

## Reading The Position Summary

Every time you move to a new position, the program prints a summary panel. It shows:

- **Move** — the move address (such as `m7-w`), whose move it was, and the move that was actually played there.
- **Turn** — which side is to move now.
- **Material** — a count of each side's pieces by value, and the balance between them. Pawns count as 1, knights and bishops as 3, rooks as 5, and the queen as 9; kings are not counted.
- **Engine** — Stockfish's score for the position and its single best move.
- **FEN** — the position written as one line of text, the standard way to describe a single chess position.

## Reading The Scores

Scores are always shown from White's point of view, so the same number means the same thing no matter whose turn it is.

- A positive number means White is better; a negative number means Black is better. The size is in pawns, so `+1.25` is a small edge for White and `-3.00` is a serious one for Black.
- A score written with `#` is a forced checkmate. `#+3` means the side to move can force mate in three; a negative mate score means the side to move is getting mated.

When you refute a move with `/w`, the program also shows an **evaluation delta**: how much the move gives up compared to the best move, measured from the mover's side. That delta is what decides the move's label, from "Best Move" down to "Blunder." The exact cutoffs are listed on the [How It Works](./architecture.md) page.

## A Worked Example

The included sample is the 1858 "Opera Game" by Paul Morphy, a short, famous attacking game that ends in checkmate on move 17. It parses to **33 half-moves**. Jump around with `/m 7-w` or `/m 8-b`, type `/eval` on an early position to see the engine's top two moves and their scores, or ask in one line with `/m 10-w, why is this a good move?`. Typing `/w <move>` on a weak move shows the refutation and a short explanation of the tactic behind it. It is a good game to learn the commands on because the finish is forced and easy to follow.

```bash
python cli.py tests/sample_game.pgn
```

For the setup this assumes, see [Local Setup](./how-to-run.md).

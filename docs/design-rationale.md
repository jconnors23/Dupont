---
hide:
  - toc
icon: material/chess-bishop
---

# Design Rationale

Why the project is built the way it is, kept as a running log of the real decisions and the reasoning behind each one. Entries are rough-dated and additive: when a decision changes, a new entry records the change rather than editing the old one away. This is working documentation for a personal prototype, not a formal architecture record.

For the layered design these decisions produced, see [How It Works](./architecture.md) and the [Dual-Engine Design](./architecture/design.md). For the plain definitions of any term used here, see the [Glossary](./glossary.md).

## The Core Decision: Engine First, Language Second

**Decision:** Put a chess engine in charge of every chess fact, and let the language model only put those facts into words.

**Why:** Pasting a PGN straight into a general chatbot (ChatGPT, Gemini) and asking about the game kept producing hallucinated game states — misremembered piece positions, invented moves, confidently wrong evaluations. A chess position is precise and rule-bound, which is exactly what a language model is unreliable at holding in its head. Rather than fight that with better prompting, the design removes the problem: the model never has to track the board, because the engine hands it the position and the evaluation as fixed facts. Everything else in the project follows from this one choice.

**What this means concretely:** the evaluation is done entirely in code by the Stockfish engine, not by any model call. The score, the best move, the lines, the refutations, and the move-quality labels are all deterministic engine output. The language model is invoked only after that calculation is finished, and only to translate it into English. It is architecturally incapable of changing a number or a move, because it is never asked to produce one. Turn the model off and every evaluation is identical — you just lose the prose.

## Why Stockfish For The Chess

**Decision:** Use Stockfish as the engine that computes moves, scores, and refutations.

**Why:** It is the strongest widely available open-source engine, it runs locally with no account or network, and the `python-chess` library speaks to it over a standard protocol out of the box. For the tactical questions this tool answers — what is the best move, how much does a move lose, what punishes it — Stockfish's deep search is exactly the right tool, and its output is deterministic, so the same position always yields the same facts.

## Why A Local Language Model (Ollama + Llama)

**Decision:** Default to a local model served by Ollama, specifically `llama3.1:8b`, through an OpenAI-compatible endpoint.

**Why, point by point:**

- **Local, not hosted.** The whole point is private, zero-cost, offline review. A cloud API would add per-request cost, rate limits, and a dependency on being online — none of which a personal review tool should need.
- **Why Ollama.** It is the simplest way to run a model locally: one install, it manages the model files, and it exposes an OpenAI-compatible endpoint so the code uses the standard `openai` client with just a changed base URL. That also means switching to another server (vLLM, llama.cpp) or even a remote API later is a config change, not a code change.
- **Why Llama 3.1 8B as the default.** It is small enough to run comfortably on modest hardware (including the laptop profile) while being capable enough to write a clear paragraph of chess explanation. Since the model only has to *explain* facts, not *compute* chess, an 8B model is enough for the default; a larger model mainly reads smoother, it does not make the chess more correct.
- **Not locked in.** The model name and endpoint are read from the environment, so trying Qwen, a larger Llama, or a remote endpoint is a one-line change in `.env`.

## Why An OpenAI-Compatible Endpoint

**Decision:** Talk to the model through the OpenAI chat-completions API shape rather than a server-specific client.

**Why:** It is the common denominator. Ollama, vLLM, llama.cpp's server, and the real OpenAI API all speak it, so the same client code works against any of them. This is what makes the model swappable by configuration alone.

## Why The Model Gets A Strict, Fact-Only System Prompt

**Decision:** Instruct the model, in the system prompt, to explain only the supplied engine facts and never to calculate moves or invent positions, and keep the model's temperature low.

**Why:** This is the enforcement side of the engine-first decision. The facts block gives the model the truth; the system prompt tells it to stay inside that truth. Low temperature keeps the wording steady and factual rather than creative. Together they make the model behave like a translator for the engine, not a second (unreliable) chess player.

## Why An Offline Fallback

**Decision:** If the model server is unreachable, print the engine facts in a readable form instead of failing.

**Why:** The engine is the source of truth and runs regardless of the model. Losing the language layer should degrade the experience to "raw but correct engine output," not to an error. So a review session still works with no model running at all — you just get the numbers and lines without the prose.

## Why The PGN Is Cleaned On Load

**Decision:** Strip header tags and anything above move 1 from the PGN when a game is loaded (`dupont/pgn_cleaner.py`).

**Why:** PGNs exported from different sites carry varying header blocks and formatting. Cutting everything down to the movetext before parsing avoids a class of parsing hiccups and keeps the loader simple, at the cost of discarding metadata the tool does not use anyway.

## Why Keyboard-First Navigation

**Decision:** Make single keypresses (`f` forward, `b` back, arrow keys) the primary way to move through a game, with typed commands for everything else.

**Why:** Reviewing a game is mostly stepping back and forth, one move at a time, while reading. Requiring a typed command and Enter for every step would be slow and break the reading rhythm. Single keys match how an online board's review mode already feels.

## Why Several Depths Of Evaluation

**Decision:** Show the engine's best move and score on every position automatically, and offer `eval` (short notes on the top two moves), `eval-long` (a full paragraph on the top move), `eval-score` (why the score is even or who is ahead), and `eval-critical` (skip to the next sharp moment and explain it). A moves-and-scores-only `eval-short` still exists but is kept off the printed command list.

**Why:** Different moments want different depth. The best move and score are always useful, so they are free on every position with no command. Beyond that: scanning a game you want a quick note (`eval`); stuck on one move you want the full reasoning (`eval-long`); unsure who stands better you want the score itself explained (`eval-score`); and when skimming you often just want to be taken to the decisive moment rather than hunting for it (`eval-critical`). Splitting the commands lets you ask for exactly as much language as the moment needs. Because the best move is already shown everywhere, the old moves-only `eval-short` became redundant for everyday use and was dropped from the manual.

## Why The Position Summary Shows What It Shows

**Decision:** On every position show the previous move, the current move number (a whole number on White's turn, a half-step like `8.5` on Black's), whose turn it is in words, the engine's best move with a plain-language description, and the score. Keep the FEN in internal state but do not print it. Keep a whole move and its two halves on screen together, clearing the screen only when you step into the next move number.

**Why:** The summary is read dozens of times per session, so it is tuned for fast reading rather than completeness. The `.5` move label answers "whose move is it?" at a glance without a separate lookup. Naming the engine's move in words ("knight moves to h6") saves the reader from decoding notation on every step. The FEN is precise but noisy and almost never read by eye, so it stays in state (where navigation and the engine still use it) rather than on screen. Clearing on a move boundary keeps the terminal from scrolling into a wall of past positions while still letting you compare White's and Black's halves of the current move.

## Why `serve` Starts The Coach From Inside The Session

**Decision:** Add a `serve` command that launches the local model server (`ollama serve`) in the background and waits until it is ready, rather than requiring the user to start it in a separate terminal first.

**Why:** The engine runs in-process, but the language model is a separate server that is easy to forget to start. Making the tool start it on request keeps the whole workflow inside the one terminal the reader is already in, and the explicit "wait until ready" means the first `eval` after `serve` does not fail on a server that is still warming up. It stays optional: the model is not needed for any engine feature, so `serve` is only there when you want written explanations.

## Why The Chess.com Paste Fix Lives In The Shell, Not The Parser

**Decision:** Fix the "can't paste a Chess.com game" problem with a zsh helper (`scripts/start-chess-com-paste.zsh`) that captures the pasted text before the shell parses it, rather than changing the PGN parser.

**Why:** The failure was diagnosed to the shell layer, not the program. A game copied with Chess.com's Share → PGN contains clock comments in curly braces (`{[%clk ...]}`); in zsh, an unquoted paste after the word `start` makes the shell throw a parse error on the braces before Python ever runs. The parser (python-chess) handles the wrapped game fine once it receives it. So the right fix is to stop the shell from mangling the input — capture the paste into a temporary file inside the line editor — and leave the proven parser alone. The clipboard and pipe input paths avoid the problem entirely and are the reliable fallback.

## Why Two Engines Are Planned (Stockfish + Lc0)

**Decision:** Plan to add Leela Chess Zero (Lc0) as an optional second engine behind the same adapter.

**Why:** Stockfish is strongest at concrete, forcing tactics; it is weaker at quiet positions where the right move is a matter of long-term judgement. Lc0's neural, self-play-trained evaluation is better in exactly those quiet positions. Having both gives the model richer facts to explain across both kinds of position. This stays consistent with the core decision — Lc0 adds more facts, not more autonomy for the model. The engine mix and the hardware behind it are detailed on the [Dual-Engine Design](./architecture/design.md) page.

## Why The RTX 5070 Ti Target

**Decision:** Target an NVIDIA RTX 5070 Ti (16 GB) for the workstation profile.

**Why:** 16 GB of GPU memory is the smallest comfortable size that can hold both the planned Lc0 neural backend and a 14B-class language model at once, fully on the GPU, at a usable speed — while staying in the price and power range of a home machine rather than a datacenter card. It is a pragmatic "runs both halves locally" target, not a performance claim.

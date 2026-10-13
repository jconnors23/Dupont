---
hide:
  - toc
icon: material/book-open-page-variant
---

# Glossary

Plain-language definitions of the terms used across these docs — both the chess and computing jargon and the project-specific ideas. Terms are grouped so you can skim to the kind you need. Where a term is explained in depth elsewhere, there is a link.

## Chess Terms

**PGN (Portable Game Notation)**
: The standard text format a chess game is saved in. It lists the moves and some header information (players, date, result). Dupont reads a PGN file as its input.

**Ply (half-move)**
: One turn by one player — the smallest unit of game progress. White playing and Black replying is two plies, which together make one numbered "move." Because a bare move number like "14" is ambiguous (White's 14th or Black's?), Dupont addresses a single ply by number *and* color, as `14-w` or `14-b` (White's 14th / Black's 14th). Internally the whole game is stored as an ordered list of plies, and the current position is just an index into that list.

**SAN (Standard Algebraic Notation)**
: The common, human-facing way moves are written. It names the piece and the destination, with symbols for captures, check, and so on: `Nf3` (knight to f3), `exd5` (pawn on the e-file captures on d5), `O-O` (kingside castling), `Qxb8+` (queen captures on b8 with check), `Rd8#` (rook to d8, checkmate). It is what you see in a PGN and in Dupont's output. Dupont accepts SAN loosely — a lowercase piece letter, a trailing `!`/`?`, or `0-0` for castling are all tolerated.

**UCI (Universal Chess Interface) move notation**
: A plainer way to write a move as just its start and end squares, like `g1f3` for the same move SAN writes as `Nf3`, or `e1g1` for kingside castling. It is unambiguous and easy for programs to parse. Dupont accepts moves in either SAN or UCI form when you name one in a question, so `why not Nxd5?` and `why not c6d5?` both work. (The acronym "UCI" is also the name of the protocol a program uses to drive an engine — a separate meaning, listed under Computing Terms.)

**FEN (Forsyth–Edwards Notation)**
: A single line of text that describes one exact board position. It has six space-separated fields: the piece layout rank by rank, whose turn it is (`w` or `b`), castling rights still available (like `KQkq`), the en-passant target square if any (`-` if none), and two move counters. For example, `rnbqkb1r/pppppppp/5n2/8/8/5N2/PPPPPPPP/RNBQKB1R b KQkq - 2 2` reads as: this exact arrangement of pieces, Black to move, both sides may still castle both ways, no en-passant square, and the two clocks.
: FEN does real work throughout Dupont, not just display. (1) **Navigation save-point:** when the game loads, every position gets its FEN stored, so jumping to a move or stepping with the arrow keys just rebuilds the board from the stored FEN instead of replaying the game from move 1. (2) **Hand-off to Stockfish:** the engine is given the position as a board rebuilt from FEN, so it needs only the current position, not the game history. (3) **A fact given to the language model:** the FEN is included in the facts block sent to the model, so the exact position is stated outright rather than left for the model to infer — this is part of why the model does not drift into a hallucinated board. (4) **A copyable readout:** it is the last line of the position summary, so you can paste the exact position into another board or engine.

**Material**
: A rough count of each side's pieces by value — pawn 1, knight and bishop 3, rook 5, queen 9. The balance tells you who is up or down material.

**Centipawn**
: One hundredth of a pawn, the unit engines use for fine-grained scores. A score of `+1.25` means White is ahead by a pawn and a quarter. The move-quality labels (Blunder, Mistake, and so on) come from centipawn cutoffs, defined on the [How It Works](./architecture.md) page.

**Principal variation (PV)**
: The line of play an engine expects to follow if both sides play its top choices. Dupont shows a few plies of the PV next to each candidate move.

**Multi-PV**
: Asking the engine for its best *several* moves at once, each with its own line, rather than just the single best. The `eval` command uses multi-PV to show the top two.

**Refutation**
: The reply that punishes a bad move. When you ask `why not <move>`, Dupont plays the move and has the engine find the opponent's best response, which is the refutation.

**Critical decision**
: A position where one move is clearly better than the alternative — the engine's top two lines differ by at least a pawn, or one of them forces checkmate. The `eval-critical` command scans forward for the next such position and explains it, so you can skip the quiet stretches and land on the moments that actually decide the game.

## Computing Terms

**REPL (Read–Eval–Print Loop)**
: The interactive command loop you type into. It **reads** your line, **evaluates** it (navigates, analyzes, or asks the coach), **prints** the result, and **loops** back for the next line. Dupont is a REPL that lives in your terminal.

**Engine (chess engine)**
: A program that calculates chess: scoring positions and finding strong moves. Dupont uses Stockfish today and plans to add Lc0.

**UCI (protocol)**
: The text protocol a chess program uses to drive an engine as a separate process. Dupont starts Stockfish and talks to it over UCI, which is why a Stockfish process spins up on launch and is shut down on exit.

**NNUE**
: Stockfish's built-in neural evaluation (an "efficiently updatable neural network"). It runs on the CPU and is what makes modern Stockfish strong at judging positions, on top of its search.

**Quantization (Q4, Q5, Q8, FP16)**
: Shrinking a language model by storing its numbers at lower precision so it fits in less memory and runs faster. `FP16` is full half-precision; `Q8`, `Q5`, and `Q4` are progressively smaller and lighter, trading a little quality for a lot less memory. The hardware profiles pick a level that fits the available memory.

**Unified memory**
: On Apple Silicon, one pool of memory shared by the CPU and GPU. It lets a laptop load a larger model than a split memory setup of the same size would, which is why the MacBook profile can run bigger quantized models.

**CUDA / TensorRT / Metal / NEON / AVX**
: Hardware acceleration backends. CUDA and TensorRT run neural work on NVIDIA GPUs; Metal is Apple's GPU framework; NEON and AVX are CPU instruction sets (Apple Silicon and x86) that speed up the math. The [Dual-Engine Design](./architecture/design.md) page says which profile uses which.

## Tools And Models

**Stockfish**
: The open-source chess engine that does all of Dupont's exact calculation — best moves, scores, and refutations. It is the source of every tactical fact the coach is allowed to use.

**Leela Chess Zero (Lc0)**
: An open-source chess engine whose name is usually shortened to "Lc0." It learned to play almost entirely from playing against itself, using a deep neural network rather than hand-written evaluation rules — the same self-play, neural-network approach made famous by DeepMind's AlphaZero. In practice it is strong at long-term positional judgement in quiet positions, which complements Stockfish's sharper tactical search. It is the planned second engine; see the [Dual-Engine Design](./architecture/design.md) page.

**Ollama**
: A tool that runs language models locally and exposes them over an OpenAI-compatible endpoint. It is Dupont's default because it is simple to install, runs fully offline on both a desktop GPU and Apple Silicon, and needs no API key or account.

**Why Ollama over other options**
: The project considered a few ways to serve the model. **Ollama** wins for everyday local use on either machine: one install, offline, no cost. **vLLM** is listed for the workstation profile because it serves faster and handles heavier models well on a dedicated GPU, at the cost of a more involved setup. **llama.cpp** underlies much of this and is the lightest option on Apple Silicon. A **remote hosted API** (such as a cloud model) is kept only as a fallback for the laptop, because it breaks the offline, zero-cost goal. All of them speak the same OpenAI-compatible protocol, so Dupont talks to any of them through one setting.

**OpenAI-compatible endpoint**
: A common web API shape that many local servers imitate. Because Ollama, vLLM, and others all expose it, Dupont can point at any of them by changing one URL, without code changes.

## Project-Specific Ideas

**Natural-language Stockfish adapter**
: The best one-line description of what Dupont is. An *adapter* sits between two things that do not speak the same language and translates between them. Here it sits between a chess engine (which speaks in numbers, move lists, and board positions) and you (asking questions in plain English). It passes your position to Stockfish, takes the engine's exact output, and has a language model render that output as readable advice. The language model never decides what is on the board or which move is best — it only translates the engine's facts into words. When Lc0 is added, the adapter is simply grounded in two engines instead of one.

**Why not "agentic"?**
: "Agentic" describes a system where a language model has autonomy — it decides what to do next, picks which tools to call, loops, and acts toward a goal with little supervision. Dupont is the opposite on purpose: the model makes no decisions about the workflow, calls nothing, and only produces one explanation per turn from facts it was given. "Adapter" (or "wrapper") is the accurate word, not "agent." Adding the second engine (Lc0) does not change this — it gives the model *more facts* to translate, not more autonomy. The design is deliberately *un*-agentic, and that constraint is the point.

**Hallucinated game state**
: What happens when you paste a PGN into a general chatbot (ChatGPT, Gemini, and the like) and ask about the game: the model loses track of where the pieces are, invents moves that were never played, and states wrong evaluations with full confidence. A chess position is precise and rule-bound, which is exactly what a language model is unreliable at holding in its head. Avoiding this is the whole reason Dupont exists — it keeps a real engine as the source of truth so the model never has to remember or judge the position itself.

**Why the RTX 5070 Ti**
: The workstation profile targets this GPU for a concrete reason: its 16 GB of memory is enough to run the planned Lc0 neural backend and a 14B-class language model at the same time, fully on the GPU, at a comfortable speed — while staying in the price and power range of a home machine rather than a datacenter card. It is the smallest setup that runs both halves of the dual-engine plan locally. The full reasoning and the alternative laptop profile are on the [Dual-Engine Design](./architecture/design.md) page.

**Anti-hallucination contract**
: The rule that the coach may only state facts the engines produced. It is why a small or large model gives the same tactical facts (only the wording differs), and why adding a second engine adds more facts to explain rather than more room to invent.

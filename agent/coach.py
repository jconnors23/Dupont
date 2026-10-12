"""agent/coach.py - Conversational Grandmaster Coach Agent.

==============================================================================
END-TO-END FLOW & PURPOSE:
==============================================================================
This module translates cold, numeric engine outputs (such as "+3.20 cp" or
"14... Qe6 15. Bxd7+ Nxd7 16. Qb8+") into intuitive, human-understandable chess
wisdom (explaining motifs like pins, overloaded pieces, and king safety).

The end-to-end flow of an interaction:
1. INPUT: The user asks a conversational question in the REPL CLI (e.g.,
   "Why is this move a mistake?" or "Why couldn't I play Nxd5 here?").
2. FACT INJECTION: Before the question is sent to the LLM, the CLI queries
   `core.engine.StockfishEngine` to compute ground-truth facts:
   - Position FEN and whose turn it is.
   - The move played in the actual game.
   - The candidate move analyzed and its classification (Blunder, Mistake, etc.).
   - The exact numerical eval drop (delta).
   - The engine's theoretical best move.
   - The opponent's concrete tactical refutation and continuation line.
3. CONTEXT AUGMENTATION: `_format_engine_facts()` builds an unambiguous structured
   facts block `[DETERMINISTIC ENGINE FACTS]` and prepends it to the user's prompt.
4. INFERENCE: The augmented prompt is appended to the session message history
   and dispatched via `openai.OpenAI` client to the model (e.g., Ollama's `llama3.1:8b`).
5. SYSTEM PROMPT CONSTRAINTS: The system prompt strictly prohibits the LLM from
   inventing piece coordinates or calculating moves independently. It is instructed
   solely to translate the provided engine facts into pedagogical concepts.
6. RESILIENCE & OFFLINE FALLBACK: If the local LLM server is offline or unreachable,
   an exception is caught gracefully and a clean deterministic markdown summary
   is generated, guaranteeing that the user is never left without analysis.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import openai
from openai import OpenAI

from core.config import config

logger = logging.getLogger(__name__)

# System prompt that establishes the persona and strictly constrains output to prevent hallucinations.
SYSTEM_PROMPT = """You are an elite, pedagogical Grandmaster chess coach assisting a student reviewing their game.

YOUR CORE MANDATES & CONSTRAINTS:
1. STRICT ANTI-HALLUCINATION: You are provided with deterministic board facts, centipawn evaluations, and Stockfish lines calculated by the engine. You must NEVER calculate or invent piece coordinates, legal moves, or alternative variations on your own.
2. BASE ALL TACTICAL POINTS ON ENGINE FACTS: Refer strictly to the provided best moves, candidate moves, and punishing refutation lines.
3. PEDAGOGICAL TRANSLATION: Do not just list engine lines. Translate the computer's variations into human, conceptual coaching insights:
   - Identify tactical motifs (e.g., forks, pins, skewers, deflections, overloaded pieces, intermediate moves/zwischenzug, back-rank weakness).
   - Explain positional and strategic consequences (e.g., king safety, piece activity, development tempo, pawn structure weaknesses, control of open files/outposts).
4. TONE & FORMAT:
   - Concise, incisive, conversational, and direct.
   - Use clear markdown formatting (bullet points, bold key terms).
   - Keep answers focused (2-4 concise paragraphs or bullet points). Avoid fluff or polite pleasantries.
"""


class ChessCoach:
    """Conversational Grandmaster coach translating engine evaluations into clear chess insights.

    For a sophomore CS student:
    Think of this class as an API client wrapper with session memory.
    It manages the HTTP connection to an OpenAI-compatible REST API (hosted locally
    by Ollama or remotely by OpenAI), maintains a conversational history buffer
    so the user can ask follow-up questions, and implements fallback error handling.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.base_url = base_url or config.LLM_BASE_URL
        self.api_key = api_key or config.OPENAI_API_KEY
        self.model = model or config.LLM_MODEL
        # Initialize OpenAI client pointing to our configured base_url
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        self.history: list[dict[str, str]] = []
        self.reset_history()

    def reset_history(self) -> None:
        """Resets conversational history back to the initial system prompt.

        In multi-turn chat completions, the LLM has no memory between HTTP requests.
        The client must pass the entire array of previous messages on each call.
        Calling this clears previous turns while preserving the foundational system prompt.
        """
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]

    def _format_engine_facts(self, facts: dict[str, Any]) -> str:
        """Formats the structured engine dictionary into an unambiguous prompt section.

        CS Concept: Grounding / Few-Shot Context Injection.
        By converting dictionary key-values into clearly labeled text blocks,
        the LLM's attention mechanism easily focuses on verified facts when generating
        the answer.
        """
        lines: list[str] = ["[DETERMINISTIC ENGINE FACTS]"]

        if "fen" in facts:
            lines.append(f"- Current Position (FEN): {facts['fen']}")
        if "turn" in facts:
            lines.append(f"- Turn: {facts['turn']}")
        if "played_move" in facts:
            lines.append(f"- Move Actually Played: {facts['played_move']}")
        if "candidate_san" in facts:
            lines.append(f"- Candidate Move Analyzed: {facts['candidate_san']}")
        if "mover_color" in facts:
            lines.append(f"- Moving Side: {facts['mover_color']}")
        if "best_move_san" in facts:
            lines.append(f"- Stockfish Best Move: {facts['best_move_san']}")
        if "best_eval_white" in facts:
            lines.append(f"- Best Move Eval (White POV): {facts['best_eval_white']}")
        if "after_eval_white" in facts:
            lines.append(f"- Eval After Move (White POV): {facts['after_eval_white']}")
        if "eval_delta_display" in facts:
            lines.append(f"- Eval Delta: {facts['eval_delta_display']}")
        if "classification" in facts:
            lines.append(f"- Move Quality Classification: {facts['classification']}")
        if "punishing_move_san" in facts and facts["punishing_move_san"]:
            opp_color = facts.get("opponent_color", "Opponent")
            lines.append(f"- {opp_color}'s Immediate Punishing Move: {facts['punishing_move_san']}")
        if "punishing_line_san" in facts and facts["punishing_line_san"]:
            lines.append(f"- Engine Punishing Continuation: {' '.join(facts['punishing_line_san'])}")

        # Top multi-PV engine lines if present
        if "lines" in facts and isinstance(facts["lines"], list) and facts["lines"]:
            lines.append("- Top Engine Candidate Lines:")
            for item in facts["lines"][:2]:
                rank = item.get("rank", 1)
                m = item.get("move", "")
                score = item.get("score_display", "")
                pv = " ".join(item.get("pv_san", [])[:5])
                lines.append(f"  * Line {rank}: {m} (Eval: {score}) -> {pv}")

        return "\n".join(lines)

    def chat(self, user_query: str, engine_facts: dict[str, Any]) -> str:
        """Sends user query accompanied by structured engine facts to the LLM coach.

        Parameters:
            user_query: The student's natural language question.
            engine_facts: Dictionary of Stockfish calculations and evaluations.

        Returns:
            The Grandmaster coach's explanation in Markdown.
        """
        # Step 1: Serialize engine facts into prompt header
        facts_block = self._format_engine_facts(engine_facts)
        user_message_content = f"{facts_block}\n\n[STUDENT QUESTION]\n{user_query.strip()}"

        # Step 2: Append to conversational history
        self.history.append({"role": "user", "content": user_message_content})

        # Step 3: Call LLM API with low temperature (0.3) for factual rigor
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.history,
                temperature=0.3,
            )
            coach_reply = response.choices[0].message.content or ""
            # Step 4: Record assistant response in history for future turns
            self.history.append({"role": "assistant", "content": coach_reply})
            return coach_reply

        except (openai.APIConnectionError, openai.APIError) as err:
            # Handle network errors or offline LLM server gracefully
            logger.warning("LLM API call failed: %s", err)
            fallback = self._generate_offline_coaching_summary(user_query, engine_facts, str(err))
            self.history.append({"role": "assistant", "content": fallback})
            return fallback

        except Exception as err:
            logger.error("Unexpected error during LLM chat: %s", err)
            fallback = self._generate_offline_coaching_summary(user_query, engine_facts, str(err))
            self.history.append({"role": "assistant", "content": fallback})
            return fallback

    def _generate_offline_coaching_summary(
        self, user_query: str, facts: dict[str, Any], error_msg: str
    ) -> str:
        """Deterministic fallback when LLM server is unreachable, displaying engine facts clearly.

        CS Concept: Graceful Degradation.
        When a non-essential service (the LLM translator) fails, the application
        does not crash with an ugly stack trace. It degrades gracefully to pure
        engine output so the student can still complete their analysis.
        """
        lines = [
            f"> *Note: LLM Coach offline ({error_msg[:120]}...). Showing deterministic engine analysis:*",
            "",
        ]

        if "candidate_san" in facts:
            lines.append(
                f"### Analysis for Move: **{facts['candidate_san']}** ({facts.get('classification', 'Evaluated')})"
            )
            lines.append(f"- **Evaluation Delta:** `{facts.get('eval_delta_display', 'N/A')}`")
            lines.append(
                f"- **Stockfish Best Move:** `{facts.get('best_move_san', 'N/A')}` (Eval: `{facts.get('best_eval_white', 'N/A')}`)"
            )
            if facts.get("punishing_move_san"):
                lines.append(
                    f"- **Punishing Refutation:** `{facts['punishing_move_san']}`"
                )
            if facts.get("punishing_line_san"):
                lines.append(
                    f"- **Continuation Line:** `{' '.join(facts['punishing_line_san'])}`"
                )
        elif "lines" in facts:
            lines.append("### Stockfish Position Evaluation")
            lines.append(f"- **FEN:** `{facts.get('fen', '')}`")
            lines.append(f"- **Best Move:** `{facts.get('best_move', 'N/A')}` (`{facts.get('best_eval', '0.00')}`)")
            for item in facts.get("lines", [])[:3]:
                pv = " ".join(item.get("pv_san", [])[:6])
                lines.append(f"- **{item['rank']}. {item['move']}** ({item['score_display']}): `{pv}`")

        return "\n".join(lines)

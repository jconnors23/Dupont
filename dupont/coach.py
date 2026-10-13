"""coach/client.py - LLM client that turns engine facts into plain-language coaching.

==============================================================================
PURPOSE
==============================================================================
This module is the language layer of the Stockfish adapter. It takes the engine's
numeric output (such as a "+3.20" evaluation or the line "14... Qe6 15. Bxd7+ Nxd7
16. Qb8+") and asks a local language model to put it into plain words, naming the
ideas behind it (pins, overloaded pieces, king safety, and the like).

The flow of one interaction:
1. The user asks a question in the CLI (e.g. "Why is this a mistake?").
2. The CLI uses `core.engine.StockfishEngine` to compute the facts for the position:
   the FEN and side to move, the move played, any candidate move and its
   classification, the evaluation and the delta, the engine's best move, and the
   opponent's refutation line.
3. `_format_engine_facts()` turns that dictionary into a labeled text block and
   prepends it to the question.
4. The combined message is sent through the `openai.OpenAI` client to the configured
   model (by default, Ollama's `llama3.1:8b`).
5. The system prompt tells the model to explain only the supplied facts and never to
   calculate moves or invent coordinates on its own.
6. If the model server is unreachable, the error is caught and a plain summary of the
   engine facts is returned instead, so the user still gets the analysis.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import openai
from openai import OpenAI

from dupont.config import config

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
        """Formats the engine-fact dictionary into a labeled text block for the prompt.

        Turning the key/values into clearly labeled lines gives the model the exact
        position and evaluation to explain, so it does not have to infer them.
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
        if "score_display" in facts:
            lines.append(f"- Evaluation (White POV): {facts['score_display']}")
        if "score_verdict" in facts:
            lines.append(f"- Score Verdict: {facts['score_verdict']}")
        if "material_white" in facts and "material_black" in facts:
            lines.append(
                f"- Material: White {facts['material_white']}, Black {facts['material_black']}"
            )
        if "options" in facts and facts["options"]:
            lines.append(f"- Options For The Side To Move: {facts['options']}")
        if "continuation" in facts and facts["continuation"]:
            lines.append(f"- Engine Continuation: {facts['continuation']}")
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

    def chat(
        self,
        user_query: str,
        engine_facts: dict[str, Any],
        system_prompt: Optional[str] = None,
    ) -> str:
        """Sends user query accompanied by structured engine facts to the LLM coach.

        Parameters:
            user_query: The student's natural language question.
            engine_facts: Dictionary of Stockfish calculations and evaluations.
            system_prompt: Optional override for the system prompt instruction.

        Returns:
            The Grandmaster coach's explanation in Markdown.
        """
        # Step 1: Serialize engine facts into prompt header
        facts_block = self._format_engine_facts(engine_facts)
        user_message_content = f"{facts_block}\n\n[STUDENT QUESTION]\n{user_query.strip()}"

        # If a specific system_prompt is provided (e.g. for /eval or /eval-long),
        # use it for this query; otherwise use the standard conversation history.
        if system_prompt:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message_content},
            ]
        else:
            self.history.append({"role": "user", "content": user_message_content})
            messages = self.history

        # Step 2: Call LLM API with low temperature (0.3) for factual rigor
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
            )
            coach_reply = response.choices[0].message.content or ""
            if not system_prompt:
                self.history.append({"role": "assistant", "content": coach_reply})
            return coach_reply

        except (openai.APIConnectionError, openai.APIError) as err:
            # Handle network errors or offline LLM server gracefully
            logger.warning("LLM API call failed: %s", err)
            fallback = self._generate_offline_coaching_summary(user_query, engine_facts, str(err))
            if not system_prompt:
                self.history.append({"role": "assistant", "content": fallback})
            return fallback

        except Exception as err:
            logger.error("Unexpected error during LLM chat: %s", err)
            fallback = self._generate_offline_coaching_summary(user_query, engine_facts, str(err))
            if not system_prompt:
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

        if "score_verdict" in facts and "candidate_san" not in facts:
            lines.append(f"### Eval score: `{facts.get('score_display', '0.00')}`")
            lines.append(f"- **Verdict:** {facts['score_verdict']}")
            if "material_white" in facts and "material_black" in facts:
                lines.append(
                    f"- **Material:** White {facts['material_white']}, Black {facts['material_black']}"
                )
            if facts.get("options"):
                lines.append(f"- **Options:** {facts['options']}")
            if facts.get("continuation"):
                lines.append(f"- **Continuation:** `{facts['continuation']}`")
        elif "candidate_san" in facts:
            lines.append(
                f"### Analysis for Move: **{facts['candidate_san']}** ({facts.get('classification', 'Evaluated')})"
            )
            if "score_display" in facts:
                lines.append(f"- **Evaluation:** `{facts['score_display']}`")
            if "eval_delta_display" in facts:
                lines.append(f"- **Evaluation Delta:** `{facts.get('eval_delta_display', 'N/A')}`")
            if "best_move_san" in facts and facts["best_move_san"] != facts["candidate_san"]:
                lines.append(
                    f"- **Stockfish Best Move:** `{facts.get('best_move_san', 'N/A')}` (Eval: `{facts.get('best_eval_white', 'N/A')}`)"
                )
            if "continuation" in facts:
                lines.append(f"- **Continuation:** `{facts['continuation']}`")
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

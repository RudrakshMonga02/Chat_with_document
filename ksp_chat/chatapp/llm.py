"""
llm.py — Strategy Pattern for LLM answer generation.

Upgraded to use Gemini's structured multi-turn contents API instead of
injecting history as plain text in a single prompt string.

Why this is better:
  - Plain text injection: Gemini reads history as a "transcript" — it has
    to parse who said what from "User: ... Assistant: ..." strings.
  - Structured turns: Gemini receives history as alternating user/model
    message objects, exactly how a real conversation is represented in the
    API. This gives much better context retention for follow-up questions.
"""

from abc import ABC, abstractmethod

from django.conf import settings
from google import genai
from google.genai import types


# ---------------------------------------------------------------------------
# Base interface
# ---------------------------------------------------------------------------
class BaseLLMStrategy(ABC):
    @abstractmethod
    def generate(self, system_prompt: str, history: list[dict], question: str) -> str:
        """
        Generate an answer given:
          system_prompt — instructions + document context (no conversation history)
          history       — list of {"role": "user"|"assistant", "content": str}
          question      — the current user question (final turn)
        """


# ---------------------------------------------------------------------------
# Gemini concrete strategy — structured multi-turn
# ---------------------------------------------------------------------------
class GeminiLLMStrategy(BaseLLMStrategy):
    """
    Sends the conversation as structured alternating user/model turns to
    Gemini instead of injecting history as a plain text block.

    Gemini API roles: "user" and "model" (not "assistant").
    """

    MODEL = "gemini-2.5-flash"

    def __init__(self):
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)

    def generate(self, system_prompt: str, history: list[dict], question: str) -> str:
        # Build structured contents list:
        # [system context as first user turn, ...history turns..., current question]
        contents = []

        # System prompt goes as the first user turn with a model acknowledgement —
        # Gemini doesn't have a dedicated system role in the basic API, so this
        # is the standard pattern for grounding the model.
        contents.append(types.Content(
            role="user",
            parts=[types.Part(text=system_prompt)],
        ))
        contents.append(types.Content(
            role="model",
            parts=[types.Part(text="Understood. I will answer questions based only on the provided document context.")],
        ))

        # Add conversation history as proper alternating turns
        for turn in history:
            gemini_role = "user" if turn["role"] == "user" else "model"
            contents.append(types.Content(
                role=gemini_role,
                parts=[types.Part(text=turn["content"])],
            ))

        # Final user turn — the actual question
        contents.append(types.Content(
            role="user",
            parts=[types.Part(text=question)],
        ))

        response = self._client.models.generate_content(
            model=self.MODEL,
            contents=contents,
        )
        return response.text

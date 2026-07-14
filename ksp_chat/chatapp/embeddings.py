"""
embeddings.py — Strategy Pattern for text embeddings.

Why a strategy here?
--------------------
Previously embed_texts() in rag.py was hardwired to Gemini. If the mentor
asks you to support OpenAI embeddings, or you want to run locally with
sentence-transformers, you'd have to dig into rag.py and risk breaking
the retrieval logic.

The Strategy Pattern fixes this:
  - BaseEmbeddingStrategy defines the interface (embed_documents, embed_query).
  - GeminiEmbeddingStrategy is the concrete Gemini implementation.
  - Any code that needs embeddings accepts a BaseEmbeddingStrategy — it doesn't
    care which provider is behind it.

How to add a new embedding provider (e.g. OpenAI):
  - Create class OpenAIEmbeddingStrategy(BaseEmbeddingStrategy).
  - Implement embed_documents() and embed_query() using the OpenAI SDK.
  - Pass an instance of it to RAGService — nothing else changes.
"""

from abc import ABC, abstractmethod

from django.conf import settings
from google import genai
from google.genai import types


# ---------------------------------------------------------------------------
# Base interface
# ---------------------------------------------------------------------------
class BaseEmbeddingStrategy(ABC):
    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of document chunks for storage."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string for retrieval."""


# ---------------------------------------------------------------------------
# Gemini concrete strategy
# ---------------------------------------------------------------------------
class GeminiEmbeddingStrategy(BaseEmbeddingStrategy):
    """
    Embedding strategy backed by Gemini's gemini-embedding-001 model.

    Uses separate task_type hints for documents vs queries — Gemini uses
    these to produce vectors that are better suited for each role
    (RETRIEVAL_DOCUMENT for chunks stored in the DB, RETRIEVAL_QUERY
    for the user's question at search time).

    NOTE: gemini-embedding-001 only accepts one text per API call, so
    both methods loop rather than batching.
    """

    MODEL = "gemini-embedding-001"

    def __init__(self):
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)

    def _embed_single(self, text: str, task_type: str) -> list[float]:
        result = self._client.models.embed_content(
            model=self.MODEL,
            contents=text,
            config=types.EmbedContentConfig(task_type=task_type),
        )
        return result.embeddings[0].values

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_single(t, "RETRIEVAL_DOCUMENT") for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_single(text, "RETRIEVAL_QUERY")

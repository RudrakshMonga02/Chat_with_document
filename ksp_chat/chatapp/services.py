"""
services.py — Service Layer pattern.

Major upgrades in this version:
  1. Multi-turn context  — history passed as structured turns to Gemini (not
                           injected as a plain text block).
  2. Cross-session RAG   — every saved message is embedded into a global
                           ChromaDB history collection. When a new question
                           comes in, we retrieve the most semantically
                           relevant messages from ALL past sessions and
                           include them as additional context.
  3. Bug fixes           — ingest() is additive, load_session correctly
                           updates the Django session key in views.py.
  4. Observability       — every pipeline step (extract, chunk, embed,
                           retrieve, generate) is timed and event-tagged via
                           log_context.log_timing, instead of only the
                           failure paths being visible.
"""

import logging

from .embeddings import BaseEmbeddingStrategy, GeminiEmbeddingStrategy
from .extractors import get_extractor
from .llm import BaseLLMStrategy, GeminiLLMStrategy
from .log_context import log_timing
from .repository import BaseVectorRepository, ChromaVectorRepository, HistoryVectorRepository

logger = logging.getLogger(__name__)


class RAGServiceError(Exception):
    """Raised when an embedding or generation call to the LLM provider fails.

    Kept deliberately generic (no provider-specific detail) since this
    message is shown to the end user; the real exception is logged instead.
    """


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
def _chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        chunk = text[start: start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


# ---------------------------------------------------------------------------
# System prompt builder — document context only, no history
# ---------------------------------------------------------------------------
def _build_system_prompt(context_chunks: list[str], source_filenames: list[str],
                         cross_session_messages: list[dict]) -> str:
    """
    Build the system prompt containing:
      - document context (retrieved chunks)
      - cross-session relevant history (RAG on past conversations)
      - instructions for the model

    Current-session history is NOT included here — it's passed as structured
    turns directly to the Gemini API (much better context retention that way).
    """
    if context_chunks:
        context_block = "\n\n---\n\n".join(context_chunks)
    else:
        context_block = "(No relevant content found across the uploaded documents.)"

    docs_line = (
        f"The user has uploaded: {', '.join(source_filenames)}."
        if source_filenames
        else "The user has uploaded one or more documents."
    )

    # Cross-session relevant history block
    if cross_session_messages:
        cs_lines = []
        for m in cross_session_messages:
            role_label = "User" if m["role"] == "user" else "Assistant"
            cs_lines.append(f"{role_label} (past session): {m['content']}")
        cross_session_block = "\n".join(cs_lines)
    else:
        cross_session_block = "(No relevant past conversations found.)"

    return f"""You are a helpful assistant answering questions about documents the user uploaded.
{docs_line}
Only use the DOCUMENT CONTEXT below to answer factual questions. If the answer isn't in the context,
say you don't know based on the uploaded documents — do not make things up.
Where relevant, mention which document the information comes from.
You may use PAST CONVERSATION CONTEXT to understand references or follow-up intent,
but always ground your answer in the document context.

DOCUMENT CONTEXT:
{context_block}

RELEVANT PAST CONVERSATION CONTEXT (from previous sessions):
{cross_session_block}

Answer clearly and concisely. Refer to document content where relevant."""


# ---------------------------------------------------------------------------
# RAGService
# ---------------------------------------------------------------------------
class RAGService:
    """
    Orchestrates the full RAG pipeline.

    Now handles two retrieval steps per query:
      1. Document retrieval  — find relevant chunks from uploaded files
      2. History retrieval   — find relevant messages from ALL past sessions

    And uses structured multi-turn Gemini API for better context retention.
    """

    def __init__(
        self,
        repository: BaseVectorRepository,
        history_repo: HistoryVectorRepository,
        embedding_strategy: BaseEmbeddingStrategy,
        llm_strategy: BaseLLMStrategy,
        session_key: str,
    ):
        self._repo = repository
        self._history_repo = history_repo
        self._embedder = embedding_strategy
        self._llm = llm_strategy
        self._session_key = session_key

    @classmethod
    def for_session(cls, session_key: str) -> "RAGService":
        return cls(
            repository=ChromaVectorRepository(session_key),
            history_repo=HistoryVectorRepository(),
            embedding_strategy=GeminiEmbeddingStrategy(),
            llm_strategy=GeminiLLMStrategy(),
            session_key=session_key,
        )

    # ── Document ingestion ────────────────────────────────────────────────────

    def ingest(self, django_file) -> dict:
        """Extract, chunk, embed, and ADD a file's chunks. Additive — no reset."""
        # NOTE: "filename" is a reserved LogRecord attribute name (the source
        # file the log call itself was made from) — logging.Logger raises
        # KeyError if extra= (which is what log_timing's **fields become)
        # tries to overwrite it, so this is doc_filename everywhere here.
        with log_timing(logger, "extraction", doc_filename=django_file.name) as result:
            extractor = get_extractor(django_file.name)
            text = extractor.extract(django_file)
            result["chars_extracted"] = len(text)

        if not text.strip():
            raise ValueError("Couldn't extract any text from that file.")

        with log_timing(logger, "chunking", doc_filename=django_file.name) as result:
            chunks = _chunk_text(text)
            result["chunk_count"] = len(chunks)

        try:
            with log_timing(logger, "embedding", doc_filename=django_file.name, chunk_count=len(chunks)):
                embeddings = self._embedder.embed_documents(chunks)
        except Exception:
            # log_timing already logged the full traceback as
            # "embedding_failed" — this is the business-level outcome on
            # top of that, not a duplicate of it.
            logger.warning(
                "Document upload failed for '%s' during embedding", django_file.name,
                extra={"event": "document_upload_failed", "doc_filename": django_file.name, "stage": "embedding"},
            )
            raise RAGServiceError(
                "Couldn't process that document right now — the embedding service is unavailable. Please try again shortly."
            ) from None

        with log_timing(logger, "vector_store_write", doc_filename=django_file.name, chunk_count=len(chunks)):
            self._repo.add(chunks, embeddings, source=django_file.name)

        return {"filename": django_file.name, "chunk_count": len(chunks)}

    def remove_document(self, filename: str):
        self._repo.remove_by_source(filename)

    # ── Message history embedding ─────────────────────────────────────────────

    def embed_and_store_message(self, message_id: int, content: str, role: str):
        """
        Embed a saved ChatMessage and store it in the global history collection.
        Called from views.py after every message is saved to the DB.
        This is what powers cross-session context retrieval.

        Best-effort: by the time this runs, the answer has already been
        generated and saved, so a failure here is logged rather than raised —
        it shouldn't turn an already-successful chat turn into an error.
        """
        try:
            embedding = self._embedder.embed_query(content)
            self._history_repo.add_message(
                message_id=message_id,
                content=content,
                embedding=embedding,
                session_key=self._session_key,
                role=role,
            )
        except Exception:
            logger.exception(
                "Failed to embed message %s into cross-session history", message_id,
                extra={"event": "embedding_failed", "stage": "history_store", "message_id": message_id},
            )

    # ── Query ─────────────────────────────────────────────────────────────────

    def query(
        self,
        question: str,
        current_session_history: list[dict],
        source_filenames: list[str],
        cross_session_keys: list[str],
    ) -> str:
        """
        Full RAG query pipeline:
          1. Embed the question
          2. Retrieve relevant document chunks (from this session's collection)
          3. Retrieve relevant past messages from cross_session_keys — the
             caller's *other* sessions (e.g. the same browser's own past
             chats), never the whole cross-user history
          4. Build system prompt with document + cross-session context
          5. Call Gemini with structured multi-turn history
        """
        try:
            with log_timing(logger, "query_embedding"):
                question_embedding = self._embedder.embed_query(question)
        except Exception:
            raise RAGServiceError(
                "Couldn't process your question right now — please try again shortly."
            ) from None

        # Step 2 — document retrieval
        with log_timing(logger, "retrieval", top_k=5) as result:
            relevant_chunks = self._repo.query(question_embedding, top_k=5)
            result["results_count"] = len(relevant_chunks)

        # Step 3 — cross-session history retrieval, scoped to the caller's
        # own other sessions (current session is excluded from this list by
        # the caller since that history is already in current_session_history)
        with log_timing(logger, "cross_session_retrieval", top_k=4) as result:
            cross_session = self._history_repo.query_relevant(
                embedding=question_embedding,
                top_k=4,
                session_keys=cross_session_keys,
            )
            result["results_count"] = len(cross_session)

        # Step 4 — system prompt (document context + cross-session context)
        system_prompt = _build_system_prompt(
            context_chunks=relevant_chunks,
            source_filenames=source_filenames,
            cross_session_messages=cross_session,
        )

        # Step 5 — structured multi-turn call
        # current_session_history goes as proper alternating turns,
        # NOT as a text block in the prompt
        try:
            with log_timing(
                logger, "llm_request",
                model=getattr(self._llm, "MODEL", type(self._llm).__name__),
            ) as result:
                answer = self._llm.generate(
                    system_prompt=system_prompt,
                    history=current_session_history,
                    question=question,
                )
                result["answer_length"] = len(answer)
        except Exception:
            raise RAGServiceError(
                "Couldn't generate an answer right now — please try again shortly."
            ) from None

        return answer

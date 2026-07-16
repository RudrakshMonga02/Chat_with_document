"""
repository.py — Repository Pattern for vector storage.

Two repositories:
  ChromaVectorRepository  — document chunks, scoped per session
  HistoryVectorRepository — message embeddings, global across all sessions
                            (used for cross-session context retrieval)
"""

import uuid
from abc import ABC, abstractmethod

import chromadb
from django.conf import settings

_chroma_client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)

# Global collection name for conversation history — all sessions share one collection,
# each message tagged with its session_key so we can filter or retrieve across sessions.
HISTORY_COLLECTION = "global_chat_history"


# ---------------------------------------------------------------------------
# Base interface
# ---------------------------------------------------------------------------
class BaseVectorRepository(ABC):
    @abstractmethod
    def add(self, texts: list[str], embeddings: list[list[float]], source: str): ...

    @abstractmethod
    def query(self, embedding: list[float], top_k: int) -> list[str]: ...

    @abstractmethod
    def reset(self): ...

    @abstractmethod
    def remove_by_source(self, source: str): ...

    @abstractmethod
    def count(self) -> int: ...


# ---------------------------------------------------------------------------
# Document chunk repository — one collection per session
# ---------------------------------------------------------------------------
class ChromaVectorRepository(BaseVectorRepository):
    def __init__(self, session_key: str):
        self._collection_name = f"session_{session_key}"
        self._collection = _chroma_client.get_or_create_collection(
            name=self._collection_name
        )

    def add(self, texts: list[str], embeddings: list[list[float]], source: str):
        if not texts:
            return
        ids = [str(uuid.uuid4()) for _ in texts]
        metadatas = [{"source": source, "chunk_index": i} for i in range(len(texts))]
        self._collection.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)

    def query(self, embedding: list[float], top_k: int) -> list[str]:
        if self.count() == 0:
            return []
        results = self._collection.query(
            query_embeddings=[embedding],
            n_results=min(top_k, self.count()),
        )
        return results["documents"][0] if results["documents"] else []

    def remove_by_source(self, source: str):
        results = self._collection.get(where={"source": source})
        ids = results.get("ids", [])
        if ids:
            self._collection.delete(ids=ids)

    def reset(self):
        """Permanently delete this session's entire collection. Every caller
        discards this repository instance right after calling reset(), so
        unlike the old version this doesn't recreate an empty collection
        afterward — that used to leave a permanent empty stub behind for
        every deleted session."""
        try:
            _chroma_client.delete_collection(name=self._collection_name)
        except Exception:
            pass  # already gone — fine

    def count(self) -> int:
        return self._collection.count()


# ---------------------------------------------------------------------------
# History repository — one global collection, all sessions
# ---------------------------------------------------------------------------
class HistoryVectorRepository:
    """
    Stores embeddings of every chat message across all sessions.
    Used to retrieve semantically relevant past messages from any session
    when building cross-session context.

    Each stored item is tagged with:
      - session_key: which session it came from
      - role: "user" or "assistant"
      - content: the message text (stored as the document itself)
    """

    def __init__(self):
        self._collection = _chroma_client.get_or_create_collection(name=HISTORY_COLLECTION)

    def add_message(self, message_id: int, content: str, embedding: list[float],
                    session_key: str, role: str):
        """Store a single message embedding. message_id from DB used as stable ID."""
        self._collection.upsert(
            ids=[f"msg_{message_id}"],
            embeddings=[embedding],
            documents=[content],
            metadatas=[{"session_key": session_key, "role": role}],
        )

    def query_relevant(self, embedding: list[float], top_k: int,
                       session_keys: list[str]) -> list[dict]:
        """
        Retrieve top_k most relevant past messages, restricted to the given
        session_keys. The caller decides what's "in scope" — e.g. a single
        browser's own other sessions — rather than searching every session
        ever created by anyone. An empty list returns nothing rather than
        falling back to an unscoped search.
        """
        if not session_keys or self._collection.count() == 0:
            return []

        results = self._collection.query(
            query_embeddings=[embedding],
            n_results=min(top_k, self._collection.count()),
            where={"session_key": {"$in": session_keys}},
        )

        items = []
        docs = results["documents"][0] if results["documents"] else []
        metas = results["metadatas"][0] if results["metadatas"] else []

        for doc, meta in zip(docs, metas):
            items.append({
                "content": doc,
                "role": meta.get("role", "user"),
                "session_key": meta.get("session_key"),
            })

        return items

    def delete_session_messages(self, session_key: str):
        """Remove all messages belonging to a deleted session."""
        results = self._collection.get(where={"session_key": session_key})
        ids = results.get("ids", [])
        if ids:
            self._collection.delete(ids=ids)

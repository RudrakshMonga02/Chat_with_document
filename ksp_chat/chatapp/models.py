"""
models.py — Database models for persistent chat history.

Three tables:
  ChatSession  — one row per conversation
  Document     — one row per uploaded file within a session (NEW)
  ChatMessage  — one row per message bubble, FK to ChatSession
"""

from django.db import models


class ChatSession(models.Model):
    session_key = models.CharField(max_length=40, unique=True, db_index=True)
    title = models.CharField(max_length=255, default="New chat")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.title} ({self.session_key[:8]}…)"


class Document(models.Model):
    """
    One row per uploaded file within a ChatSession.

    session     — FK to ChatSession; CASCADE so documents are cleaned up
                  when a session is deleted.
    filename    — original filename (e.g. "report.pdf"); also used as the
                  `source` tag on ChromaDB chunk metadata so we can delete
                  only that file's chunks when a document is removed.
    chunk_count — how many chunks were stored; useful for display/debugging.
    uploaded_at — auto-set timestamp.
    """

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    filename = models.CharField(max_length=255)
    chunk_count = models.IntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]
        # Prevent uploading the same filename twice in the same session
        unique_together = [("session", "filename")]

    def __str__(self):
        return f"{self.filename} ({self.chunk_count} chunks)"


class ChatMessage(models.Model):
    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_CHOICES = [
        (ROLE_USER, "User"),
        (ROLE_ASSISTANT, "Assistant"),
    ]

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        preview = self.content[:60] + ("…" if len(self.content) > 60 else "")
        return f"[{self.role}] {preview}"

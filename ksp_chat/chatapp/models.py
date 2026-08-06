"""
models.py — Database models for persistent chat history.

Four tables:
  AppUser      — one row per username seen from the external JWT auth
                 service (NEW). Never stores a password or email — that's
                 owned entirely by that service. Lazily created the first
                 time a valid token for that username is seen.
  ChatSession  — one row per conversation
  Document     — one row per uploaded file within a session
  ChatMessage  — one row per message bubble, FK to ChatSession
"""

from django.db import models


class AppUser(models.Model):
    username = models.CharField(max_length=150, unique=True, db_index=True)
    # Immutable IdP-issued identifier — groundwork for the day the external
    # auth service's JWT starts carrying one (see
    # chatapp.authentication.extract_subject_id). Nullable/unique-when-set:
    # every row works exactly as before (looked up by username) until then.
    # Once populated, this becomes the real identity join key instead of the
    # mutable username, so a rename/reuse on the IdP side can't silently
    # merge a new account into an old one's chat history.
    subject_id = models.CharField(max_length=255, unique=True, null=True, blank=True, db_index=True)
    # Local-only revocation: the auth service is never told about this and
    # keeps considering an inactive user's token perfectly valid. Setting
    # this to False just means JWTAuthenticationMiddleware stops honoring
    # that token here — same name/convention as django.contrib.auth's own
    # User.is_active, used the same way (soft-disable, not a real delete).
    is_active = models.BooleanField(default=True)
    # A cached copy of the auth service's own `role` JWT claim — that
    # service is the source of truth, this is just a local shadow so
    # admin_views.admin_users_page can display it without an extra network
    # call. Kept fresh by JWTAuthenticationMiddleware/auth_views.login_view
    # on every request/login that carries a token for this user.
    # admin_views.create_user also sets this (always to ROLE_USER, eagerly,
    # before the new account has ever logged in) — see that view's own
    # comment for why it's hardcoded rather than read from the request.
    ROLE_USER = "user"
    ROLE_ADMIN = "admin"
    ROLE_CHOICES = [(ROLE_USER, "User"), (ROLE_ADMIN, "Admin")]
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_USER)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.username


class ChatSession(models.Model):
    session_key = models.CharField(max_length=40, unique=True, db_index=True)
    title = models.CharField(max_length=255, default="New chat")
    # Set once the user manually renames the chat — stops upload/remove from
    # silently overwriting their chosen name with an auto-generated one.
    title_locked = models.BooleanField(default=False)
    # SET_NULL rather than CASCADE so an AppUser row disappearing (e.g. an
    # admin removing the account) never silently destroys chat history —
    # removing a user's data is a separate, explicit action (see
    # views.remove_user), not a side effect of deleting the AppUser row.
    owner = models.ForeignKey(
        AppUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_sessions",
    )
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

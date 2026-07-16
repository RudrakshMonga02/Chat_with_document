"""
views.py — HTTP layer only.

Bug fixes in this version:
  1. chat_api guard checks DB for documents (not ephemeral session variable)
  2. load_session updates the Django session key so the server knows which
     session is active — fixes "please upload a document" after switching sessions
  3. Every saved message is embedded into global history for cross-session RAG
  4. delete_session also cleans up history embeddings
  5. session_key resolution (override-aware) is now shared by every view that
     needs it — previously upload_file used the raw Django session key even
     while browsing a loaded past session, silently attaching new documents
     to the wrong ChatSession
  6. sessions are now scoped per-browser via a lightweight cookie (see
     _get_owned_session_keys/_remember_owned_session) — previously the
     sidebar and load/delete/remove-document endpoints exposed and accepted
     every ChatSession in the database, not just the requester's own
  7. cross-session RAG (chat_api) is now scoped to that same owned-sessions
     list instead of the entire cross-user history
  8. rename_session lets a chat be renamed any number of times; once
     renamed, upload/remove-document stop overwriting the title
     (ChatSession.title_locked)
  9. login is now mandatory: index uses login_required (redirects to
     /login/), every AJAX endpoint uses jwt_required (401 JSON, since
     chat.js is what's calling them, not a page navigation). The anonymous
     owned-sessions-cookie scoping in _visible_session_keys is harmless
     dead weight now that every request reaching these views is
     authenticated, but it's left in place rather than ripped out
"""

import json
import logging

from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .authentication import get_request_username, jwt_required, login_required
from .models import AppUser, ChatMessage, ChatSession, Document
from .services import RAGService, RAGServiceError

logger = logging.getLogger(__name__)

# Cookie that remembers which session_keys this browser has created, so the
# sidebar/load/delete/remove-document endpoints can be scoped to "mine"
# without requiring accounts. Separate from Django's session cookie, which
# rotates on "New chat" and session deletion.
OWNED_SESSIONS_COOKIE = "owned_sessions"
OWNED_SESSIONS_MAX_AGE = 60 * 60 * 24 * 400  # ~400 days: the browser-enforced cap on cookie lifetime
MAX_OWNED_SESSIONS = 50  # keeps the cookie comfortably under the ~4KB per-cookie limit


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ensure_session(request):
    if not request.session.session_key:
        request.session.create()


def _resolve_active_session_key(request) -> str:
    """The session the caller is currently 'looking at' — the loaded-session
    override if one is set (via the sidebar), otherwise their own live
    Django session. Shared by every view so they all agree on which session
    is active."""
    return request.session.get("_active_session_key_override") or request.session.session_key


def _get_or_create_chat_session(request, session_key: str) -> ChatSession:
    obj, _ = ChatSession.objects.get_or_create(session_key=session_key)
    # Claim it for the logged-in account the first time we see it unowned —
    # covers both a brand new session and an old anonymous one that predates login.
    username = get_request_username(request)
    if username and obj.owner_id is None:
        app_user, _ = AppUser.objects.get_or_create(username=username)
        obj.owner = app_user
        obj.save(update_fields=["owner"])
    return obj


def _get_owned_session_keys(request) -> list[str]:
    raw = request.COOKIES.get(OWNED_SESSIONS_COOKIE, "")
    return [k for k in raw.split(",") if k]


def _write_owned_cookie(response, keys: list[str]):
    trimmed = keys[-MAX_OWNED_SESSIONS:]
    response.set_cookie(
        OWNED_SESSIONS_COOKIE,
        ",".join(trimmed),
        max_age=OWNED_SESSIONS_MAX_AGE,
        httponly=True,
        samesite="Lax",
    )


def _remember_owned_session(response, request, session_key: str):
    keys = _get_owned_session_keys(request)
    if session_key in keys:
        return
    _write_owned_cookie(response, keys + [session_key])


def _owns_session(request, session_key: str, owned_keys) -> bool:
    """Whether this request is allowed to view/act on session_key: it's in
    the owned-sessions cookie, it's the browser's own live/loaded Django
    session (covers the moment right before the cookie is written), or —
    logged in — it belongs to the same account regardless of which browser
    created it."""
    if (
        session_key in owned_keys
        or session_key == request.session.session_key
        or session_key == request.session.get("_active_session_key_override")
    ):
        return True
    username = get_request_username(request)
    if username:
        return ChatSession.objects.filter(session_key=session_key, owner__username=username).exists()
    return False


def _visible_session_keys(request) -> list[str]:
    """Every session_key this request should see in the sidebar: the
    browser's own cookie-scoped anonymous sessions, plus — if logged in —
    every session tied to that account, regardless of which browser or
    device created it."""
    keys = set(_get_owned_session_keys(request))
    username = get_request_username(request)
    if username:
        keys.update(ChatSession.objects.filter(owner__username=username).values_list("session_key", flat=True))
    return list(keys)


def _session_list(session_keys):
    return list(
        ChatSession.objects.filter(session_key__in=session_keys)
        .values("id", "title", "session_key", "updated_at")
    )


def _doc_list(chat_session: ChatSession) -> list[dict]:
    return list(chat_session.documents.values("id", "filename", "chunk_count"))


# ── Views ─────────────────────────────────────────────────────────────────────

@login_required
def index(request):
    _ensure_session(request)
    session_key = _resolve_active_session_key(request)

    chat_session = ChatSession.objects.filter(session_key=session_key).first()
    chat_history = (
        list(chat_session.messages.values("role", "content")) if chat_session else []
    )
    documents = _doc_list(chat_session) if chat_session else []

    return render(request, "chatapp/index.html", {
        "chat_history": chat_history,
        "documents": documents,
        "sessions": _session_list(_visible_session_keys(request)),
        "active_session_key": session_key,
        "auth_username": get_request_username(request),
    })


@require_http_methods(["POST"])
@jwt_required
def upload_file(request):
    _ensure_session(request)
    session_key = _resolve_active_session_key(request)

    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"error": "No file was uploaded."}, status=400)

    chat_session = _get_or_create_chat_session(request, session_key)

    if chat_session.documents.filter(filename=uploaded.name).exists():
        return JsonResponse(
            {"error": f"'{uploaded.name}' is already uploaded in this session."},
            status=400,
        )

    try:
        service = RAGService.for_session(session_key)
        result = service.ingest(uploaded)
    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)
    except RAGServiceError as e:
        return JsonResponse({"error": str(e)}, status=502)

    try:
        Document.objects.create(
            session=chat_session,
            filename=result["filename"],
            chunk_count=result["chunk_count"],
        )
    except IntegrityError:
        # Another upload of the same filename in this session won the race
        # between our .exists() check above and this create().
        return JsonResponse(
            {"error": f"'{uploaded.name}' is already uploaded in this session."},
            status=400,
        )

    if not chat_session.title_locked:
        existing_count = chat_session.documents.count()
        if existing_count == 1:
            chat_session.title = result["filename"]
        else:
            chat_session.title = f"{chat_session.documents.first().filename} +{existing_count - 1} more"
    chat_session.save()

    visible_keys = list(set(_visible_session_keys(request)) | {session_key})
    response = JsonResponse({
        "filename": result["filename"],
        "chunk_count": result["chunk_count"],
        "message": f"'{result['filename']}' added ({result['chunk_count']} chunks).",
        "documents": _doc_list(chat_session),
        "sessions": _session_list(visible_keys),
    })
    _remember_owned_session(response, request, session_key)
    return response


@require_http_methods(["DELETE"])
@jwt_required
def remove_document(request, document_id):
    owned_keys = _get_owned_session_keys(request)

    try:
        doc = Document.objects.select_related("session").get(id=document_id)
    except Document.DoesNotExist:
        return JsonResponse({"error": "Document not found."}, status=404)

    chat_session = doc.session
    if not _owns_session(request, chat_session.session_key, owned_keys):
        # Don't reveal that a document with this id exists elsewhere.
        return JsonResponse({"error": "Document not found."}, status=404)

    doc.delete()  # its Chroma chunks are cleaned up by the post_delete signal in signals.py

    if not chat_session.title_locked:
        remaining = list(chat_session.documents.all())
        if not remaining:
            chat_session.title = "New chat"
        elif len(remaining) == 1:
            chat_session.title = remaining[0].filename
        else:
            chat_session.title = f"{remaining[0].filename} +{len(remaining) - 1} more"
    chat_session.save()

    visible_keys = list(set(_visible_session_keys(request)) | {chat_session.session_key})
    return JsonResponse({
        "documents": _doc_list(chat_session),
        "sessions": _session_list(visible_keys),
    })


@require_http_methods(["POST"])
@jwt_required
def chat_api(request):
    _ensure_session(request)
    session_key = _resolve_active_session_key(request)

    # BUG FIX 1: check DB for documents, not the ephemeral session variable.
    # This works correctly after server restarts and after switching sessions.
    chat_session = ChatSession.objects.filter(session_key=session_key).first()
    if not chat_session or not chat_session.documents.exists():
        return JsonResponse(
            {"error": "Please upload at least one document before asking questions."},
            status=400,
        )

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    question = (body.get("question") or "").strip()
    if not question:
        return JsonResponse({"error": "Question cannot be empty."}, status=400)

    # Last 10 messages = 5 turns of current session context
    recent = list(chat_session.messages.order_by("-created_at")[:10])
    recent.reverse()
    current_history = [{"role": m.role, "content": m.content} for m in recent]

    source_filenames = list(chat_session.documents.values_list("filename", flat=True))

    # Cross-session context is scoped to sessions this request can see —
    # this browser's own anonymous sessions, plus every session on the same
    # account if logged in — never the whole cross-user history (see
    # HistoryVectorRepository.query_relevant).
    cross_session_keys = [k for k in _visible_session_keys(request) if k != session_key]

    service = RAGService.for_session(session_key)
    try:
        answer = service.query(question, current_history, source_filenames, cross_session_keys)
    except RAGServiceError as e:
        return JsonResponse({"error": str(e)}, status=502)

    # Save both turns to DB
    user_msg = ChatMessage.objects.create(session=chat_session, role="user", content=question)
    asst_msg = ChatMessage.objects.create(session=chat_session, role="assistant", content=answer)
    chat_session.save()

    # Embed both messages into global history for cross-session RAG.
    # Best-effort: the answer has already been generated and saved above,
    # so a failure here shouldn't turn into an error response to the user.
    service.embed_and_store_message(user_msg.id, question, "user")
    service.embed_and_store_message(asst_msg.id, answer, "assistant")

    return JsonResponse({"answer": answer})


@require_http_methods(["POST"])
@jwt_required
def new_session(request):
    _ensure_session(request)

    # Clean up the old session's ChromaDB collection before abandoning it.
    # Without this, every "New chat" click leaves an orphaned collection on disk.
    old_key = request.session.session_key
    if old_key:
        old_chat_session = ChatSession.objects.filter(session_key=old_key).first()
        # Only wipe ChromaDB if there's no DB row keeping it alive —
        # i.e. it's a ghost session (never uploaded anything, never got a title)
        if not old_chat_session:
            try:
                from .repository import ChromaVectorRepository
                ChromaVectorRepository(old_key).reset()
            except Exception:
                logger.warning("Failed to reset Chroma collection for ghost session %s", old_key, exc_info=True)

    request.session.flush()
    request.session.create()

    return JsonResponse({
        "sessions": _session_list(_visible_session_keys(request)),
        "new_session_key": request.session.session_key,
    })


@require_http_methods(["GET"])
@jwt_required
def load_session(request, session_key):
    owned_keys = _get_owned_session_keys(request)
    if not _owns_session(request, session_key, owned_keys):
        return JsonResponse({"error": "Session not found."}, status=404)

    try:
        chat_session = ChatSession.objects.get(session_key=session_key)
    except ChatSession.DoesNotExist:
        return JsonResponse({"error": "Session not found."}, status=404)

    messages = list(chat_session.messages.values("role", "content"))

    # BUG FIX 2: update the Django session so the server knows this session
    # is now active. Without this, chat_api still sees the old session key
    # after switching sessions, causing the "upload a document first" error.
    request.session["_active_session_key_override"] = session_key
    request.session.modified = True

    return JsonResponse({
        "messages": messages,
        "documents": _doc_list(chat_session),
        "session_key": session_key,
    })


@require_http_methods(["DELETE"])
@jwt_required
def delete_session(request, session_key):
    owned_keys = _get_owned_session_keys(request)
    if not _owns_session(request, session_key, owned_keys):
        return JsonResponse({"error": "Session not found."}, status=404)

    try:
        chat_session = ChatSession.objects.get(session_key=session_key)
    except ChatSession.DoesNotExist:
        return JsonResponse({"error": "Session not found."}, status=404)

    # If the deleted session was the browser's active one, flush the stale
    # cookie and immediately create a fresh session so the browser gets a
    # new valid cookie. Without this, the next request arrives with a stale
    # key that matches nothing, and Django silently creates a new session
    # anyway — but the browser still thinks it's carrying the deleted key,
    # causing ghost-state bugs.
    was_active = (
        request.session.session_key == session_key
        or request.session.get("_active_session_key_override") == session_key
    )

    # Chroma/history cleanup happens via the post_delete signal in signals.py
    # so it runs consistently regardless of where the delete is triggered from
    # (this view, the admin, a shell command, etc).
    chat_session.delete()

    if was_active:
        request.session.flush()
        request.session.create()

    remaining_owned = [k for k in owned_keys if k != session_key]
    remaining_visible = [k for k in _visible_session_keys(request) if k != session_key]
    response = JsonResponse({
        "sessions": _session_list(remaining_visible),
        "new_session_key": request.session.session_key if was_active else None,
    })
    _write_owned_cookie(response, remaining_owned)
    return response


@require_http_methods(["POST"])
@jwt_required
def rename_session(request, session_key):
    owned_keys = _get_owned_session_keys(request)
    if not _owns_session(request, session_key, owned_keys):
        return JsonResponse({"error": "Session not found."}, status=404)

    try:
        chat_session = ChatSession.objects.get(session_key=session_key)
    except ChatSession.DoesNotExist:
        return JsonResponse({"error": "Session not found."}, status=404)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    new_title = (body.get("title") or "").strip()
    if not new_title:
        return JsonResponse({"error": "Chat name cannot be empty."}, status=400)

    # Once renamed, upload_file/remove_document stop overwriting the title —
    # see ChatSession.title_locked. The user can rename again at any time.
    chat_session.title = new_title[:255]
    chat_session.title_locked = True
    chat_session.save()

    visible_keys = list(set(_visible_session_keys(request)) | {session_key})
    return JsonResponse({
        "title": chat_session.title,
        "sessions": _session_list(visible_keys),
    })

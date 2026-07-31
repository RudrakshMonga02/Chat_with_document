"""
views.py — HTTP layer only.

"""

import json
import logging

from django.conf import settings
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .authentication import get_request_username, jwt_required, login_required
from .models import AppUser, ChatMessage, ChatSession, Document
from .services import RAGService, RAGServiceError

logger = logging.getLogger(__name__)

RECENT_LOGS_MAX_LINES = 2000


def _read_recent_logs(username: str, max_lines=RECENT_LOGS_MAX_LINES):
    """The last max_lines of app.log belonging to username, in the same
    shape the live websocket sends (see logging_handlers.ChannelsLogHandler),
    so the frontend renders history and live lines identically. app.log is
    always written as one JSON object per line (settings.LOGGING's "file"
    handler always uses JSONFormatter, regardless of LOG_FORMAT) specifically
    so this can parse it directly instead of reverse-engineering a
    human-oriented text format the way this used to work."""
    log_path = settings.BASE_DIR / "logs" / "app.log"
    if not log_path.exists():
        return []

    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()[-max_lines:]

    entries = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            continue  # a line from before JSON logging existed, or a partial write
        if record.get("username") != username:
            continue
        entries.append({
            "level": record.get("level"),
            "logger": record.get("logger"),
            "message": record.get("message"),
            "time": record.get("timestamp_epoch"),
        })
    return entries

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


def _session_belongs_to_caller(chat_session: ChatSession, request) -> bool:
    """The one ownership check _get_or_create_chat_session and
    _resolve_active_chat_session both need: an unclaimed session (no owner
    yet) belongs to anyone; a claimed one belongs only to the matching
    authenticated username. Factored out so the two call sites can't drift
    out of sync with each other.

    _owns_session below has a related but distinct check — it starts from
    a bare session_key with no ChatSession fetched yet, and has its own
    fast path for a session that doesn't have a row at all — so it's kept
    separate rather than forced through this helper."""
    if chat_session.owner_id is None:
        return True
    username = get_request_username(request)
    return bool(username) and chat_session.owner.username == username


def _get_or_create_chat_session(request, session_key: str) -> ChatSession:
    username = get_request_username(request)
    obj, created = ChatSession.objects.get_or_create(session_key=session_key)

    if not created and not _session_belongs_to_caller(obj, request):
        # session_key resolves to somebody else's chat — a stale/reused
        # browser cookie, most likely. Login/logout now rotate the session
        # specifically to prevent this, but never trust that alone: reusing
        # or silently re-owning another account's ChatSession here would
        # mean this upload lands in their data. Mint a fresh session instead.
        logger.warning(
            "Refusing to reuse ChatSession %s (owned by '%s') for authenticated user '%s' — rotating to a new session",
            session_key, obj.owner.username, username,
            extra={"event": "session_ownership_conflict", "session_key": session_key},
        )
        request.session.flush()
        request.session.create()
        obj = ChatSession.objects.create(session_key=request.session.session_key)

    if username and obj.owner_id is None:
        app_user, _ = AppUser.objects.get_or_create(username=username)
        obj.owner = app_user
        obj.save(update_fields=["owner"])
    return obj


def _resolve_active_chat_session(request, session_key: str) -> ChatSession | None:
    """The ChatSession tied to session_key, but only if it isn't owned by
    someone else. Defense-in-depth, independent of the login/logout session
    rotation: even if a stale or reused session_key somehow survives to
    reach here, this guarantees it can never surface another account's
    chat history or documents — it's treated as if there's no active
    session at all rather than silently shown."""
    chat_session = ChatSession.objects.filter(session_key=session_key).first()
    if chat_session is None:
        return None
    if not _session_belongs_to_caller(chat_session, request):
        return None
    return chat_session


def _owns_session(request, session_key: str) -> bool:
    """Whether this request is allowed to view/act on session_key: it's the
    browser's own live/loaded Django session (covers the moment right
    before a ChatSession row exists yet), or — the authoritative check,
    since login is mandatory — it belongs to the same account."""
    if (
        session_key == request.session.session_key
        or session_key == request.session.get("_active_session_key_override")
    ):
        return True
    username = get_request_username(request)
    if username:
        return ChatSession.objects.filter(session_key=session_key, owner__username=username).exists()
    return False


def _visible_session_keys(request) -> list[str]:
    """Every session_key this request should see in the sidebar: every
    session owned by the logged-in account, regardless of which browser or
    device created it."""
    username = get_request_username(request)
    if not username:
        return []
    return list(ChatSession.objects.filter(owner__username=username).values_list("session_key", flat=True))


def _session_list(session_keys):
    return list(
        ChatSession.objects.filter(session_key__in=session_keys)
        .values("id", "title", "session_key", "updated_at")
    )


def _doc_list(chat_session: ChatSession) -> list[dict]:
    return list(chat_session.documents.values("id", "filename", "chunk_count"))


# ── Views ─────────────────────────────────────────────────────────────────────

@login_required
def logs_page(request):
    username = get_request_username(request)
    return render(request, "chatapp/logs.html", {
        "auth_username": username,
        "initial_logs": _read_recent_logs(username),
    })


@login_required
def index(request):
    _ensure_session(request)
    session_key = _resolve_active_session_key(request)
    username = get_request_username(request)

    chat_session = _resolve_active_chat_session(request, session_key)
    chat_history = (
        list(chat_session.messages.values("role", "content")) if chat_session else []
    )
    documents = _doc_list(chat_session) if chat_session else []

    return render(request, "chatapp/index.html", {
        "chat_history": chat_history,
        "documents": documents,
        "sessions": _session_list(_visible_session_keys(request)),
        "active_session_key": session_key,
        "auth_username": username,
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
    # May differ from the value above — _get_or_create_chat_session rotates
    # to a fresh session_key if the original one belonged to someone else.
    # Everything below (RAGService, cookie, response) must use the real one.
    session_key = chat_session.session_key

    if chat_session.documents.filter(filename=uploaded.name).exists():
        return JsonResponse(
            {"error": f"'{uploaded.name}' is already uploaded in this session."},
            status=400,
        )

    logger.info(
        "Document upload started: '%s' in session %s", uploaded.name, session_key,
        # NOTE: "filename" is a reserved LogRecord attribute name (the
        # source file the log call was made from) — logging.Logger raises
        # KeyError if extra= tries to overwrite it, so this field is named
        # doc_filename throughout, not filename.
        extra={"event": "document_upload_started", "session_key": session_key, "doc_filename": uploaded.name},
    )

    try:
        service = RAGService.for_session(session_key)
        result = service.ingest(uploaded)
    except ValueError as e:
        logger.warning(
            "Document upload rejected: '%s' — %s", uploaded.name, e,
            extra={
                "event": "document_upload_failed",
                "session_key": session_key,
                "doc_filename": uploaded.name,
                "reason": "invalid_file",
            },
        )
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

    logger.info(
        "Document '%s' uploaded to session %s (%d chunks)", result["filename"], session_key, result["chunk_count"],
        extra={
            "event": "document_upload_completed",
            "session_key": session_key,
            "doc_filename": result["filename"],
            "chunk_count": result["chunk_count"],
        },
    )

    visible_keys = list(set(_visible_session_keys(request)) | {session_key})
    return JsonResponse({
        "filename": result["filename"],
        "chunk_count": result["chunk_count"],
        "message": f"'{result['filename']}' added ({result['chunk_count']} chunks).",
        "documents": _doc_list(chat_session),
        "sessions": _session_list(visible_keys),
    })


@require_http_methods(["DELETE"])
@jwt_required
def remove_document(request, document_id):
    try:
        doc = Document.objects.select_related("session").get(id=document_id)
    except Document.DoesNotExist:
        return JsonResponse({"error": "Document not found."}, status=404)

    chat_session = doc.session
    if not _owns_session(request, chat_session.session_key):
        # Don't reveal that a document with this id exists elsewhere.
        return JsonResponse({"error": "Document not found."}, status=404)

    filename = doc.filename
    doc.delete()  # its Chroma chunks are cleaned up by the post_delete signal in signals.py
    logger.info(
        "Document '%s' removed from session %s", filename, chat_session.session_key,
        extra={"event": "document_removed", "session_key": chat_session.session_key, "doc_filename": filename},
    )

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
    chat_session = _resolve_active_chat_session(request, session_key)
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

    logger.info(
        "Question asked in session %s: %s", session_key, question[:200],
        extra={"event": "chat_message_received", "session_key": session_key},
    )

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

    logger.info(
        "Answer generated for session %s (%d chars)", session_key, len(answer),
        extra={"event": "chat_message_answered", "session_key": session_key, "answer_length": len(answer)},
    )

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

    logger.info(
        "New chat session created: %s", request.session.session_key,
        extra={"event": "session_created", "session_key": request.session.session_key},
    )

    return JsonResponse({
        "sessions": _session_list(_visible_session_keys(request)),
        "new_session_key": request.session.session_key,
    })


@require_http_methods(["GET"])
@jwt_required
def load_session(request, session_key):
    if not _owns_session(request, session_key):
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
    if not _owns_session(request, session_key):
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
    logger.info(
        "Chat session deleted: %s", session_key,
        extra={"event": "session_deleted", "session_key": session_key},
    )

    if was_active:
        request.session.flush()
        request.session.create()

    remaining_visible = [k for k in _visible_session_keys(request) if k != session_key]
    return JsonResponse({
        "sessions": _session_list(remaining_visible),
        "new_session_key": request.session.session_key if was_active else None,
    })


@require_http_methods(["POST"])
@jwt_required
def rename_session(request, session_key):
    if not _owns_session(request, session_key):
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

    logger.info(
        "Session %s renamed to '%s'", session_key, chat_session.title,
        extra={"event": "session_renamed", "session_key": session_key},
    )

    visible_keys = list(set(_visible_session_keys(request)) | {session_key})
    return JsonResponse({
        "title": chat_session.title,
        "sessions": _session_list(visible_keys),
    })

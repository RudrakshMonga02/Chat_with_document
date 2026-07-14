"""
views.py — HTTP layer only.

Bug fixes in this version:
  1. chat_api guard checks DB for documents (not ephemeral session variable)
  2. load_session updates the Django session key so the server knows which
     session is active — fixes "please upload a document" after switching sessions
  3. Every saved message is embedded into global history for cross-session RAG
  4. delete_session also cleans up history embeddings
"""

import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .models import ChatMessage, ChatSession, Document
from .services import RAGService


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ensure_session(request):
    if not request.session.session_key:
        request.session.create()


def _get_or_create_chat_session(session_key: str) -> ChatSession:
    obj, _ = ChatSession.objects.get_or_create(session_key=session_key)
    return obj


def _session_list():
    return list(ChatSession.objects.values("id", "title", "session_key", "updated_at"))


def _doc_list(chat_session: ChatSession) -> list[dict]:
    return list(chat_session.documents.values("id", "filename", "chunk_count"))


# ── Views ─────────────────────────────────────────────────────────────────────

def index(request):
    _ensure_session(request)
    session_key = request.session.session_key

    chat_session = ChatSession.objects.filter(session_key=session_key).first()
    chat_history = (
        list(chat_session.messages.values("role", "content")) if chat_session else []
    )
    documents = _doc_list(chat_session) if chat_session else []

    return render(request, "chatapp/index.html", {
        "chat_history": chat_history,
        "documents": documents,
        "sessions": _session_list(),
        "active_session_key": session_key,
    })


@require_http_methods(["POST"])
def upload_file(request):
    _ensure_session(request)
    session_key = request.session.session_key

    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"error": "No file was uploaded."}, status=400)

    chat_session = _get_or_create_chat_session(session_key)

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

    Document.objects.create(
        session=chat_session,
        filename=result["filename"],
        chunk_count=result["chunk_count"],
    )

    existing_count = chat_session.documents.count()
    if existing_count == 1:
        chat_session.title = result["filename"]
    else:
        chat_session.title = f"{chat_session.documents.first().filename} +{existing_count - 1} more"
    chat_session.save()

    return JsonResponse({
        "filename": result["filename"],
        "chunk_count": result["chunk_count"],
        "message": f"'{result['filename']}' added ({result['chunk_count']} chunks).",
        "documents": _doc_list(chat_session),
        "sessions": _session_list(),
    })


@require_http_methods(["DELETE"])
def remove_document(request, document_id):
    try:
        doc = Document.objects.select_related("session").get(id=document_id)
    except Document.DoesNotExist:
        return JsonResponse({"error": "Document not found."}, status=404)

    chat_session = doc.session
    session_key = chat_session.session_key
    filename = doc.filename

    RAGService.for_session(session_key).remove_document(filename)
    doc.delete()

    remaining = list(chat_session.documents.all())
    if not remaining:
        chat_session.title = "New chat"
    elif len(remaining) == 1:
        chat_session.title = remaining[0].filename
    else:
        chat_session.title = f"{remaining[0].filename} +{len(remaining) - 1} more"
    chat_session.save()

    return JsonResponse({
        "documents": _doc_list(chat_session),
        "sessions": _session_list(),
    })


@require_http_methods(["POST"])
def chat_api(request):
    _ensure_session(request)

    # BUG FIX 2 (part 2): when a past session is loaded via the sidebar,
    # load_session stores its key as an override. Use that if present,
    # otherwise fall back to the Django session key (current session).
    session_key = (
        request.session.get("_active_session_key_override")
        or request.session.session_key
    )

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

    service = RAGService.for_session(session_key)
    answer = service.query(question, current_history, source_filenames)

    # Save both turns to DB
    user_msg = ChatMessage.objects.create(session=chat_session, role="user", content=question)
    asst_msg = ChatMessage.objects.create(session=chat_session, role="assistant", content=answer)
    chat_session.save()

    # Embed both messages into global history for cross-session RAG
    service.embed_and_store_message(user_msg.id, question, "user")
    service.embed_and_store_message(asst_msg.id, answer, "assistant")

    return JsonResponse({"answer": answer})


@require_http_methods(["POST"])
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
                pass  # collection may not exist yet — fine

    request.session.flush()
    request.session.create()

    return JsonResponse({
        "sessions": _session_list(),
        "new_session_key": request.session.session_key,
    })


@require_http_methods(["GET"])
def load_session(request, session_key):
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
def delete_session(request, session_key):
    try:
        chat_session = ChatSession.objects.get(session_key=session_key)
    except ChatSession.DoesNotExist:
        return JsonResponse({"error": "Session not found."}, status=404)

    service = RAGService.for_session(session_key)
    service.delete_session_history()  # clean up history embeddings
    service._repo.reset()             # clean up document chunk embeddings

    chat_session.delete()

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
    if was_active:
        request.session.flush()
        request.session.create()

    return JsonResponse({
        "sessions": _session_list(),
        "new_session_key": request.session.session_key if was_active else None,
    })

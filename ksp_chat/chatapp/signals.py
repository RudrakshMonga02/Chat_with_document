"""
signals.py — keep ChromaDB vectors in sync with ChatSession/Document deletions.

Deleting a row anywhere other than the normal views (e.g. via the Django
admin, or `.delete()` in a shell) previously left its Chroma vectors
orphaned on disk forever — that's exactly what the cleanup_chroma
management command was written to mop up after the fact. This makes the
cleanup automatic and unconditional, regardless of how the row was deleted.
"""

import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import ChatSession, Document

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=ChatSession)
def cleanup_chroma_for_session(sender, instance, **kwargs):
    from .repository import ChromaVectorRepository, HistoryVectorRepository

    session_key = instance.session_key
    try:
        ChromaVectorRepository(session_key).reset()
    except Exception:
        logger.exception("Failed to clean up Chroma collection for session %s", session_key)
    try:
        HistoryVectorRepository().delete_session_messages(session_key)
    except Exception:
        logger.exception("Failed to clean up history embeddings for session %s", session_key)


@receiver(post_delete, sender=Document)
def cleanup_chroma_for_document(sender, instance, **kwargs):
    from .repository import ChromaVectorRepository

    # If the parent session is gone too (cascade delete), the signal above
    # already wiped the whole collection — nothing left to do here.
    session_key = ChatSession.objects.filter(pk=instance.session_id).values_list(
        "session_key", flat=True
    ).first()
    if not session_key:
        return

    try:
        ChromaVectorRepository(session_key).remove_by_source(instance.filename)
    except Exception:
        logger.exception(
            "Failed to clean up Chroma chunks for document '%s' in session %s",
            instance.filename, session_key,
        )

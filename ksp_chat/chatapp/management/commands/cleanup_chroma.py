"""
Management command: python manage.py cleanup_chroma

Scans all ChromaDB collections and deletes any that have no matching
ChatSession row in the DB — i.e. orphaned collections left behind by
old "New chat" clicks or stale sessions.

Run once to clean up existing orphans. Safe to re-run at any time.
"""

import chromadb
from django.conf import settings
from django.core.management.base import BaseCommand

from chatapp.models import ChatSession


class Command(BaseCommand):
    help = "Delete orphaned ChromaDB collections with no matching ChatSession in the DB."

    def handle(self, *args, **options):
        client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        all_collections = client.list_collections()

        # Build set of valid session keys from DB
        valid_keys = set(ChatSession.objects.values_list("session_key", flat=True))

        # Global history collection — never delete this one
        PROTECTED = {"global_chat_history"}

        deleted = 0
        kept = 0

        for col in all_collections:
            name = col.name
            if name in PROTECTED:
                kept += 1
                continue

            # Session collections are named "session_<key>"
            if name.startswith("session_"):
                key = name[len("session_"):]
                if key not in valid_keys:
                    client.delete_collection(name)
                    self.stdout.write(self.style.WARNING(f"  Deleted orphan: {name}"))
                    deleted += 1
                else:
                    kept += 1
            else:
                # Unknown collection — skip safely
                kept += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Deleted {deleted} orphaned collection(s), kept {kept}."
        ))

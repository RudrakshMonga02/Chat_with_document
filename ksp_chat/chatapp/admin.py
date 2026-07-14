from django.contrib import admin
from .models import ChatMessage, ChatSession, Document


class DocumentInline(admin.TabularInline):
    model = Document
    readonly_fields = ("filename", "chunk_count", "uploaded_at")
    extra = 0


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    readonly_fields = ("role", "content", "created_at")
    extra = 0


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ("title", "session_key", "created_at", "updated_at")
    list_filter = ("created_at",)
    search_fields = ("title", "session_key")
    readonly_fields = ("session_key", "created_at", "updated_at")
    inlines = [DocumentInline, ChatMessageInline]


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("filename", "session", "chunk_count", "uploaded_at")
    readonly_fields = ("session", "filename", "chunk_count", "uploaded_at")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("session", "role", "short_content", "created_at")
    list_filter = ("role", "created_at")
    search_fields = ("content",)
    readonly_fields = ("session", "role", "content", "created_at")

    @admin.display(description="Content preview")
    def short_content(self, obj):
        return obj.content[:80] + ("…" if len(obj.content) > 80 else "")

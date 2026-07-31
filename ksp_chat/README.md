# KSP Document Chat — RAG Chatbot (Django + Gemini + ChromaDB)

An authenticated RAG chatbot: register/log in, upload PDF/TXT documents, then ask
questions about them. Each account can have several named chat sessions, each with
its own documents and history, plus an admin dashboard and a live log viewer.

## How it works

1. Register/log in — credentials are proxied to an external JWT auth service (see
   **Authentication** below); this app never stores a password itself.
2. Upload a PDF/TXT → text is extracted, split into overlapping chunks, embedded via
   Gemini (`gemini-embedding-001`), and stored in a ChromaDB collection scoped to the
   active chat session. Uploading is additive — a session can hold several documents.
3. Ask a question → the question is embedded, the most relevant chunks are retrieved
   from the session's collection *and* from a global cross-session history (so the
   assistant can draw on relevant context from your other past chats), and Gemini
   (`gemini-2.5-flash`) answers grounded in that context.
4. Accounts, chat sessions, documents, and messages live in the database (SQLite by
   default); ChromaDB persists vectors to disk (`chroma_db/`); application logs are
   written as JSON lines to `logs/app.log` and streamed live to the `/logs/` page.

## Authentication

This app is a **resource server only** — login/registration/logout are thin proxies
to an external FastAPI JWT auth service (`AUTH_SERVICE_BASE_URL`), which owns
credentials and token issuance. There are two more, entirely separate identities
worth knowing about:

- A single hardcoded admin account (`ADMIN_USERNAME`/`ADMIN_PASSWORD`) for this app's
  own small dashboard at `/users/` — lets you view registered accounts and ban one.
- Django's own built-in admin site at `/admin/` (`django.contrib.auth`'s
  `User`/`is_staff`/`is_superuser`) — off by default (see `DJANGO_ADMIN_ENABLED`
  below), since it's unrelated to both systems above.

## Project layout

```
chatapp/
  services.py          <- RAGService: extraction -> chunking -> embedding -> retrieval -> generation
  repository.py         <- ChromaDB repositories (per-session documents + cross-session history)
  embeddings.py / llm.py / extractors.py   <- Strategy/Factory implementations (Gemini, PDF/TXT)
  authentication.py / middleware.py / channels_auth.py   <- JWT verification, request context
  auth_views.py         <- login/register/logout (proxied to the external auth service)
  admin_auth.py / admin_views.py           <- this app's own single-admin dashboard (/users/)
  consumers.py / routing.py / logging_handlers.py / log_context.py  <- live log viewer
  views.py              <- chat/session/document HTTP endpoints
  models.py             <- AppUser, ChatSession, Document, ChatMessage
templates/chatapp/       <- login, register, chat, admin dashboard, live logs pages
static/chatapp/           <- css/js for each page
chroma_db/                <- ChromaDB's persisted vector data (created automatically)
logs/app.log              <- structured (JSON-lines) application log
```

## Setup

1. Create a virtual environment (recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file next to `manage.py` with at least `GEMINI_API_KEY` and the
   `AUTH_JWT_*` values — see **Configuration** below for the full list.

4. Run migrations:
   ```bash
   python manage.py migrate
   ```

5. Start the dev server:
   ```bash
   python manage.py runserver
   ```

6. Open http://127.0.0.1:8000/ → register a new account (or log in) → upload a PDF
   or TXT → start chatting.
   - Admin dashboard: http://127.0.0.1:8000/users/ (needs `ADMIN_USERNAME`/
     `ADMIN_PASSWORD` set)
   - Live logs: http://127.0.0.1:8000/logs/ (any logged-in account, unless
     `LOG_VIEWER_USERS` restricts it)

## Configuration

All of these are read from a `.env` file next to `manage.py` (via `python-dotenv`).

**Core**
| Variable | Default | Notes |
|---|---|---|
| `DJANGO_SECRET_KEY` | dev-only fallback | Set a real one for any non-local deployment. |
| `DJANGO_DEBUG` | `True` | Set `False` outside local dev. |
| `DJANGO_ALLOWED_HOSTS` | *(empty)* | Comma-separated hostnames; required when `DJANGO_DEBUG=False`. |
| `GEMINI_API_KEY` | *(empty)* | From https://aistudio.google.com/apikey — required for upload/chat to work. |

**Authentication** (external JWT auth service — a separate project)
| Variable | Default | Notes |
|---|---|---|
| `AUTH_SERVICE_BASE_URL` | `http://127.0.0.1:8001` | Where login/register/logout are proxied to. |
| `AUTH_JWT_SECRET_KEY` | *(empty)* | Must match the auth service's own signing secret exactly, or every token fails verification — left unset, login simply won't work yet. |
| `AUTH_JWT_ALGORITHM` | `HS256` | Must match the auth service. |
| `AUTH_JWT_EXPECTED_ISS` | *(empty, skipped)* | Optional hardening — only set this once the auth service actually sends an `iss` claim; turning it on before then locks everyone out. |
| `AUTH_JWT_EXPECTED_AUD` | *(empty, skipped)* | Same, for the `aud` claim. |

**This app's own admin dashboard** (`/users/`) — unrelated to the auth service above
| Variable | Default | Notes |
|---|---|---|
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | *(empty)* | A single hardcoded admin identity. Left unset, `/users/` is simply unreachable. |

**Django's built-in admin site** (`/admin/`) — a third, separate identity system
| Variable | Default | Notes |
|---|---|---|
| `DJANGO_ADMIN_ENABLED` | `False` | Only set `True` if you deliberately want `/admin/` reachable (its own `django.contrib.auth` superuser system) — e.g. for local DB inspection. |

**Live log viewer** (`/logs/`)
| Variable | Default | Notes |
|---|---|---|
| `LOG_VIEWER_USERS` | *(empty = any logged-in account)* | Comma-separated usernames allowed to open the live log page/socket. |
| `LOG_LEVEL` | `DEBUG` if `DJANGO_DEBUG=True`, else `INFO` | Level for the `chatapp` logger. |
| `LOG_FORMAT` | `text` if `DJANGO_DEBUG=True`, else `json` | Only affects the console handler — `logs/app.log` is always JSON, one object per line. |

## Notes for review

- `services.py`/`repository.py`/`embeddings.py`/`llm.py`/`extractors.py` split the RAG
  pipeline by responsibility (Service Layer / Repository / Strategy / Factory
  patterns), so the embedding/LLM provider, vector storage, and file-type support can
  each be swapped independently.
- Documents and chat history are scoped per chat session and owned by an account —
  a user can have several named sessions, each with its own documents, and the
  assistant can also draw on relevant context from that user's other past sessions.
- Uploading is additive: adding a document to a session keeps the existing ones and
  their embeddings intact.
- Chunking uses a simple character-based sliding window (1000 chars, 150-char
  overlap) — no LangChain dependency, easy to explain/tweak.

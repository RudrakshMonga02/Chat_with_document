# KSP Document Chat — RAG Chatbot (Django + Gemini + ChromaDB)

A minimal RAG chatbot: upload a PDF/TXT file, then ask questions about it.
No login — each browser session gets its own isolated document + chat history.

## How it works

1. Upload a PDF/TXT → text is extracted, split into overlapping chunks,
   embedded via Gemini (`gemini-embedding-001`), and stored in a ChromaDB
   collection scoped to your session.
2. Ask a question → your question is embedded, the most relevant chunks are
   retrieved from your session's collection, and Gemini (`gemini-2.5-flash`)
   answers using those chunks as context.
3. Chat history is stored in Django's session (cookie-based) — no database
   table needed for it.

## Project layout

```
chatapp/
  rag.py        <- all RAG logic: extraction, chunking, embedding, retrieval, generation
  views.py      <- thin HTTP layer (index, upload_file, chat_api)
  urls.py
templates/chatapp/index.html   <- single-page UI
static/chatapp/css/style.css
static/chatapp/js/chat.js      <- fetch() calls to /upload/ and /chat/
chroma_db/      <- ChromaDB's persisted vector data (created automatically)
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

3. Get a Gemini API key from https://aistudio.google.com/apikey and set it
   as an environment variable:
   ```bash
   export GEMINI_API_KEY="your-key-here"        # macOS/Linux
   set GEMINI_API_KEY=your-key-here              # Windows cmd
   $env:GEMINI_API_KEY="your-key-here"           # Windows PowerShell
   ```

4. Run migrations (only needed for Django's built-in session table):
   ```bash
   python manage.py migrate
   ```

5. Start the dev server:
   ```bash
   python manage.py runserver
   ```

6. Open http://127.0.0.1:8000/ — upload a PDF or TXT, then start chatting.

## Notes for review

- `rag.py` is intentionally separate from `views.py` to keep RAG logic
  testable and reusable, and views focused only on HTTP request/response.
- Sessions (not user accounts) isolate documents: each Chroma collection is
  named `session_<django_session_key>`, so two visitors never see each
  other's documents.
- Uploading a new file resets that session's Chroma collection and clears
  chat history, since old answers no longer apply to a different document.
- Chunking uses a simple character-based sliding window (1000 chars,
  150-char overlap) — no LangChain dependency, easy to explain/tweak.

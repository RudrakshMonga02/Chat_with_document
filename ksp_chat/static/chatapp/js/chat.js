// chat.js — document dropdown, dark mode, upload, chat, sidebar, sessions.

// ── CSRF ─────────────────────────────────────────────────────────────────────
function getCsrfToken() {
    const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : "";
}

// ── DOM refs ──────────────────────────────────────────────────────────────────
const htmlEl            = document.documentElement;
const layout            = document.getElementById("layout");
const toggleBtn         = document.getElementById("toggle-btn");
const sessionList       = document.getElementById("session-list");
const newChatBtn        = document.getElementById("new-chat-btn");

const docDropdownWrapper= document.getElementById("doc-dropdown-wrapper");
const docSummaryBtn     = document.getElementById("doc-summary-btn");
const docSummaryText    = document.getElementById("doc-summary-text");
const docDropdownList   = document.getElementById("doc-dropdown-list");
const uploadStatus      = document.getElementById("upload-status");
const fileInput         = document.getElementById("file-input");

const themeToggleBtn    = document.getElementById("theme-toggle-btn");
const themeIcon         = document.getElementById("theme-icon");

const chatWindow        = document.getElementById("chat-window");
const chatForm          = document.getElementById("chat-form");
const questionInput     = document.getElementById("question-input");
const sendButton        = document.getElementById("send-button");

const contextMenu       = document.getElementById("context-menu");
const contextDeleteBtn  = document.getElementById("context-delete-btn");
const modalOverlay      = document.getElementById("modal-overlay");
const modalChatName     = document.getElementById("modal-chat-name");
const modalCancel       = document.getElementById("modal-cancel");
const modalDelete       = document.getElementById("modal-delete");

let activeSessionKey = window.ACTIVE_SESSION_KEY || "";
let pendingDeleteKey = null;

// ── Dark mode ─────────────────────────────────────────────────────────────────
function setTheme(dark) {
    htmlEl.setAttribute("data-theme", dark ? "dark" : "light");
    themeIcon.textContent = dark ? "☀️" : "🌙";
    localStorage.setItem("theme", dark ? "dark" : "light");
}

// Restore saved theme preference on load
const savedTheme = localStorage.getItem("theme");
setTheme(savedTheme === "dark");

themeToggleBtn.addEventListener("click", () => {
    setTheme(htmlEl.getAttribute("data-theme") !== "dark");
});

// ── Sidebar toggle ────────────────────────────────────────────────────────────
function setSidebar(open) {
    layout.classList.toggle("sidebar-collapsed", !open);
    localStorage.setItem("sidebarOpen", open ? "1" : "0");
}

const savedSidebar = localStorage.getItem("sidebarOpen");
setSidebar(savedSidebar === null ? true : savedSidebar === "1");

toggleBtn.addEventListener("click", () => {
    setSidebar(layout.classList.contains("sidebar-collapsed"));
});

// ── Document dropdown open/close ──────────────────────────────────────────────
// Using JS mouseenter/mouseleave on the WHOLE wrapper (pill + dropdown panel)
// instead of CSS :hover on just the pill — this eliminates the gap-disappear
// bug where moving the cursor from pill to panel briefly left the wrapper,
// instantly hiding the dropdown before you could reach it.

let dropdownCloseTimer = null;

docDropdownWrapper.addEventListener("mouseenter", () => {
    clearTimeout(dropdownCloseTimer);
    docDropdownWrapper.classList.add("open");
});

docDropdownWrapper.addEventListener("mouseleave", () => {
    // Small delay before closing — gives the cursor time to move between
    // the pill and the panel without triggering a flicker.
    dropdownCloseTimer = setTimeout(() => {
        docDropdownWrapper.classList.remove("open");
    }, 120);
});

// Also toggle on click for touch/keyboard users
docSummaryBtn.addEventListener("click", () => {
    docDropdownWrapper.classList.toggle("open");
});

// Close dropdown when clicking anywhere outside it
document.addEventListener("click", (e) => {
    if (!docDropdownWrapper.contains(e.target)) {
        docDropdownWrapper.classList.remove("open");
    }
});

// ── Document dropdown helpers ─────────────────────────────────────────────────
function docDropdownItemHTML(doc) {
    return `
        <div class="doc-dropdown-item" data-id="${doc.id}">
            <span class="doc-icon">📄</span>
            <span class="doc-name" title="${doc.filename}">${doc.filename}</span>
            <span class="doc-chunks">${doc.chunk_count}c</span>
            <button class="doc-remove-btn"
                    data-id="${doc.id}"
                    data-name="${doc.filename}"
                    title="Remove">✕</button>
        </div>`;
}

function updateDocSummary(docs) {
    if (!docs || docs.length === 0) {
        docSummaryText.textContent = "📄 No documents";
    } else if (docs.length === 1) {
        docSummaryText.textContent = `📄 ${docs[0].filename}`;
    } else {
        docSummaryText.textContent = `📄 ${docs.length} documents`;
    }
}

function renderDocDropdown(docs) {
    if (!docs || docs.length === 0) {
        docDropdownList.innerHTML = `<p class="doc-empty-hint">No documents uploaded yet.</p>`;
    } else {
        docDropdownList.innerHTML = docs.map(docDropdownItemHTML).join("");
    }
    updateDocSummary(docs);
    attachDocRemoveHandlers();
}

function attachDocRemoveHandlers() {
    docDropdownList.querySelectorAll(".doc-remove-btn").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            removeDocument(btn.dataset.id, btn.dataset.name);
        });
    });
}

// ── File upload ───────────────────────────────────────────────────────────────
fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    if (!file) return;

    uploadStatus.textContent = `Processing "${file.name}"…`;
    uploadStatus.className = "upload-status";
    fileInput.value = "";

    const formData = new FormData();
    formData.append("file", file);

    try {
        const res = await fetch("/upload/", {
            method: "POST",
            headers: { "X-CSRFToken": getCsrfToken() },
            body: formData,
        });
        const data = await res.json();

        if (!res.ok) {
            uploadStatus.textContent = data.error || "Upload failed.";
            uploadStatus.className = "upload-status error";
            return;
        }

        uploadStatus.textContent = data.message;
        uploadStatus.className = "upload-status success";

        renderDocDropdown(data.documents);
        if (data.sessions) renderSessionList(data.sessions);
        setActiveItem(activeSessionKey);

        if (!chatWindow.querySelector(".bubble")) {
            clearChat("Documents ready. Ask anything about them.");
        }
    } catch {
        uploadStatus.textContent = "Something went wrong uploading the file.";
        uploadStatus.className = "upload-status error";
    }
});

// ── Remove document ───────────────────────────────────────────────────────────
async function removeDocument(docId, docName) {
    try {
        const res = await fetch(`/remove-document/${docId}/`, {
            method: "DELETE",
            headers: { "X-CSRFToken": getCsrfToken() },
        });
        const data = await res.json();
        if (!res.ok) return;

        uploadStatus.textContent = `"${docName}" removed.`;
        uploadStatus.className = "upload-status success";

        renderDocDropdown(data.documents);
        if (data.sessions) renderSessionList(data.sessions);

        if (!data.documents || data.documents.length === 0) {
            clearChat();
        }
    } catch {
        uploadStatus.textContent = "Failed to remove document.";
        uploadStatus.className = "upload-status error";
    }
}

// ── Chat window helpers ───────────────────────────────────────────────────────
function clearChat(hint = "Upload one or more documents above, then ask anything about them.") {
    chatWindow.innerHTML = `<div class="empty-state" id="empty-state"><p>${hint}</p></div>`;
}

function removeEmptyState() {
    const el = document.getElementById("empty-state");
    if (el) el.remove();
}

function addBubble(role, text) {
    removeEmptyState();
    const bubble = document.createElement("div");
    bubble.className = `bubble ${role}`;
    bubble.textContent = text;
    chatWindow.appendChild(bubble);
    chatWindow.scrollTop = chatWindow.scrollHeight;
    return bubble;
}

// ── Chat ──────────────────────────────────────────────────────────────────────
chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const question = questionInput.value.trim();
    if (!question) return;

    addBubble("user", question);
    questionInput.value = "";
    sendButton.disabled = true;

    const pendingBubble = addBubble("assistant pending", "Thinking…");

    try {
        const res = await fetch("/chat/", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCsrfToken(),
            },
            body: JSON.stringify({ question }),
        });
        const data = await res.json();
        pendingBubble.classList.remove("pending");
        pendingBubble.textContent = res.ok ? data.answer : (data.error || "Something went wrong.");
    } catch {
        pendingBubble.classList.remove("pending");
        pendingBubble.textContent = "Network error — please try again.";
    } finally {
        sendButton.disabled = false;
        questionInput.focus();
    }
});

// ── Session list ──────────────────────────────────────────────────────────────
function truncate(str, n) {
    return str.length > n ? str.slice(0, n - 1) + "…" : str;
}

function setActiveItem(key) {
    sessionList.querySelectorAll(".session-item").forEach(el => {
        el.classList.toggle("active", el.dataset.key === key);
    });
}

function attachSessionHandlers() {
    sessionList.querySelectorAll(".session-item").forEach(item => {
        item.addEventListener("click", (e) => {
            if (e.target.closest(".session-menu-btn")) return;
            loadSession(item.dataset.key);
        });
    });
    sessionList.querySelectorAll(".session-menu-btn").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            showContextMenu(e, btn.dataset.key, btn.dataset.title);
        });
    });
}

function renderSessionList(sessions) {
    if (!sessions || sessions.length === 0) {
        sessionList.innerHTML = `<p class="sidebar-hint">Your chats will appear here.</p>`;
        return;
    }
    sessionList.innerHTML = sessions.map(s => `
        <div class="session-item ${s.session_key === activeSessionKey ? "active" : ""}"
             data-key="${s.session_key}" data-title="${s.title}">
            <span class="session-icon">💬</span>
            <span class="session-label">${truncate(s.title, 22)}</span>
            <button class="session-menu-btn"
                    data-key="${s.session_key}"
                    data-title="${s.title}"
                    title="Options">&#8942;</button>
        </div>
    `).join("");
    attachSessionHandlers();
}

// ── New chat ──────────────────────────────────────────────────────────────────
newChatBtn.addEventListener("click", async () => {
    try {
        const res = await fetch("/new-session/", {
            method: "POST",
            headers: { "X-CSRFToken": getCsrfToken() },
        });
        const data = await res.json();
        activeSessionKey = data.new_session_key;

        clearChat();
        renderDocDropdown([]);
        uploadStatus.textContent = "";
        uploadStatus.className = "upload-status";
        questionInput.value = "";

        if (data.sessions) renderSessionList(data.sessions);
    } catch {
        console.error("Failed to create new session.");
    }
});

// ── Load past session ─────────────────────────────────────────────────────────
async function loadSession(sessionKey) {
    if (sessionKey === activeSessionKey) return;

    try {
        const res = await fetch(`/load-session/${sessionKey}/`);
        const data = await res.json();
        if (!res.ok) return;

        activeSessionKey = data.session_key || sessionKey;
        setActiveItem(activeSessionKey);

        renderDocDropdown(data.documents);
        uploadStatus.textContent = "";
        uploadStatus.className = "upload-status";

        chatWindow.innerHTML = "";
        if (!data.messages || !data.messages.length) {
            clearChat("No messages yet in this session.");
        } else {
            data.messages.forEach(m => addBubble(m.role, m.content));
        }
    } catch {
        console.error("Failed to load session.");
    }
}

// ── Context menu ──────────────────────────────────────────────────────────────
function showContextMenu(e, sessionKey, sessionTitle) {
    pendingDeleteKey = sessionKey;
    contextMenu.style.top  = `${e.clientY}px`;
    contextMenu.style.left = `${e.clientX}px`;
    contextMenu.classList.add("visible");
    contextDeleteBtn.dataset.title = sessionTitle;
}

function hideContextMenu() { contextMenu.classList.remove("visible"); }

document.addEventListener("click", (e) => {
    if (!contextMenu.contains(e.target)) hideContextMenu();
});

contextDeleteBtn.addEventListener("click", () => {
    hideContextMenu();
    modalChatName.textContent = `"${contextDeleteBtn.dataset.title}"`;
    modalOverlay.classList.add("visible");
});

// ── Delete session modal ──────────────────────────────────────────────────────
modalCancel.addEventListener("click", () => {
    modalOverlay.classList.remove("visible");
    pendingDeleteKey = null;
});

modalOverlay.addEventListener("click", (e) => {
    if (e.target === modalOverlay) {
        modalOverlay.classList.remove("visible");
        pendingDeleteKey = null;
    }
});

modalDelete.addEventListener("click", async () => {
    if (!pendingDeleteKey) return;
    const keyToDelete = pendingDeleteKey;
    pendingDeleteKey = null;
    modalOverlay.classList.remove("visible");

    try {
        const res = await fetch(`/delete-session/${keyToDelete}/`, {
            method: "DELETE",
            headers: { "X-CSRFToken": getCsrfToken() },
        });
        const data = await res.json();
        if (!res.ok) return;

        if (keyToDelete === activeSessionKey) {
            // Server gave us a fresh session key — update so next request
            // uses the new valid session, not the deleted stale one
            if (data.new_session_key) {
                activeSessionKey = data.new_session_key;
            } else {
                activeSessionKey = "";
            }
            clearChat();
            renderDocDropdown([]);
            uploadStatus.textContent = "";
            uploadStatus.className = "upload-status";
        }

        if (data.sessions !== undefined) renderSessionList(data.sessions);
    } catch {
        console.error("Failed to delete session.");
    }
});

// ── Init — wire handlers on page-load rendered elements ───────────────────────
attachSessionHandlers();
attachDocRemoveHandlers();

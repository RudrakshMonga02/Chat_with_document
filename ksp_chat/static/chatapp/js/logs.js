// logs.js — live log viewer for the /logs/ page.
// Kept separate from chat.js (which expects many chat-specific DOM
// elements) so this page's simpler DOM can't cause null-ref errors there,
// and vice versa.

const htmlEl      = document.documentElement;
const layout      = document.getElementById("layout");
const toggleBtn   = document.getElementById("toggle-btn");
const logsConsole = document.getElementById("logs-console");
const logsStatus  = document.getElementById("logs-status");

// ── Theme + sidebar state — mirrors chat.js so both pages stay in sync ──────
htmlEl.setAttribute("data-theme", localStorage.getItem("theme") === "dark" ? "dark" : "light");

function setSidebar(open) {
    layout.classList.toggle("sidebar-collapsed", !open);
    localStorage.setItem("sidebarOpen", open ? "1" : "0");
}
const savedSidebar = localStorage.getItem("sidebarOpen");
setSidebar(savedSidebar === null ? true : savedSidebar === "1");

toggleBtn.addEventListener("click", () => {
    setSidebar(layout.classList.contains("sidebar-collapsed"));
});

// ── Live log stream ──────────────────────────────────────────────────────────
function setStatus(text, cls) {
    logsStatus.textContent = text;
    logsStatus.className = "logs-status " + cls;
}

function appendLog(log) {
    const line = document.createElement("div");
    line.className = "log-line level-" + log.level;

    const timeSpan = document.createElement("span");
    timeSpan.className = "log-time";
    timeSpan.textContent = new Date(log.time * 1000).toLocaleTimeString();

    const levelSpan = document.createElement("span");
    levelSpan.className = "log-level";
    levelSpan.textContent = log.level;

    const msgSpan = document.createElement("span");
    msgSpan.className = "log-message";
    msgSpan.textContent = log.message;

    line.append(timeSpan, levelSpan, msgSpan);
    logsConsole.appendChild(line);
    logsConsole.scrollTop = logsConsole.scrollHeight;
}

// ── Seed with recent history from the log file, so a reload doesn't wipe
// the console back to empty — only the live socket connection is new. ──────
const initialLogsEl = document.getElementById("initial-logs-data");
if (initialLogsEl) {
    JSON.parse(initialLogsEl.textContent).forEach(appendLog);
}

function connect() {
    setStatus("Connecting…", "connecting");
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${proto}//${window.location.host}/ws/logs/`);

    socket.onopen = () => setStatus("Live", "connected");
    socket.onmessage = (e) => appendLog(JSON.parse(e.data));
    socket.onclose = () => {
        setStatus("Disconnected — retrying…", "disconnected");
        setTimeout(connect, 2000);
    };
    socket.onerror = () => socket.close();
}

connect();

// admin_users.js — the admin "manage users" page. No sidebar/theme-toggle
// logic here (unlike chat.js/logs.js) — this shell has neither; it's a
// deliberately simpler, separate surface from the chat app.

function getCsrfToken() {
    const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : "";
}

document.getElementById("users-table-body").addEventListener("click", async (e) => {
    const btn = e.target.closest(".user-remove-btn");
    if (!btn) return;

    const username = btn.dataset.username;
    const confirmed = confirm(
        `Remove "${username}"? This deletes their chats and revokes their access to this app.`
    );
    if (!confirmed) return;

    btn.disabled = true;
    try {
        const res = await fetch(`/users/${encodeURIComponent(username)}/`, {
            method: "DELETE",
            headers: { "X-CSRFToken": getCsrfToken() },
        });
        const data = await res.json();
        if (!res.ok) {
            alert(data.error || "Failed to remove user.");
            btn.disabled = false;
            return;
        }
        const row = document.querySelector(`tr[data-username="${CSS.escape(username)}"]`);
        if (row) row.remove();
    } catch {
        alert("Network error — please try again.");
        btn.disabled = false;
    }
});

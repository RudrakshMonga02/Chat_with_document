// admin_users.js — the admin "manage users" page. No sidebar/theme-toggle
// logic here (unlike chat.js/logs.js) — this shell has neither; it's a
// deliberately simpler, separate surface from the chat app.

function getCsrfToken() {
    const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : "";
}

function userRow(u) {
    const tr = document.createElement("tr");
    tr.dataset.username = u.username;
    tr.innerHTML = `
        <td>${u.username}</td>
        <td><span class="role-badge ${u.role}">${u.role}</span></td>
        <td><span class="status-badge active">Active</span></td>
        <td>${u.chat_session_count}</td>
        <td>—</td>
        <td class="users-table-actions">
            <button class="user-remove-btn" data-username="${u.username}">Remove</button>
        </td>
    `;
    return tr;
}

const createUserForm = document.getElementById("create-user-form");
const createUserError = document.getElementById("create-user-error");

createUserForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    createUserError.hidden = true;

    const formData = new FormData(createUserForm);
    const submitBtn = createUserForm.querySelector("button[type='submit']");
    submitBtn.disabled = true;

    try {
        const res = await fetch("/users/create/", {
            method: "POST",
            headers: { "X-CSRFToken": getCsrfToken(), "Content-Type": "application/json" },
            body: JSON.stringify({
                username: formData.get("username"),
                password: formData.get("password"),
            }),
        });
        const data = await res.json();
        if (!res.ok) {
            createUserError.textContent = data.error || "Failed to create user.";
            createUserError.hidden = false;
            return;
        }

        const emptyRow = document.querySelector(".users-table-empty");
        if (emptyRow) emptyRow.closest("tr").remove();
        document.getElementById("users-table-body").appendChild(userRow(data));
        createUserForm.reset();
    } catch {
        createUserError.textContent = "Network error — please try again.";
        createUserError.hidden = false;
    } finally {
        submitBtn.disabled = false;
    }
});

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

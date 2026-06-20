const api = {
    users: "/api/users/",
    rules: "/api/reward-rules/",
    rewards: "/api/rewards/",
    events: "/api/events/",
    balance: "/api/balance/",
    ledger: "/api/ledger/",
    redeem: "/api/redeem/",
};

const state = {
    users: [],
    rules: [],
    rewards: [],
};

let eventLookupTimer = null;
const messageTimers = new WeakMap();

function byId(id) {
    return document.getElementById(id);
}

function messageText(payload) {
    if (typeof payload === "string") {
        return payload;
    }
    const text = payload.message || payload.error || JSON.stringify(payload);
    return payload.details ? `${text} ${payload.details}` : text;
}

function showMessage(element, payload, type = "success") {
    if (!element) {
        return;
    }
    const baseClass = element.dataset.messageBase || (element.classList.contains("result-box") ? "result-box" : "message");
    const existingTimer = messageTimers.get(element);
    if (existingTimer) {
        window.clearTimeout(existingTimer);
    }
    element.dataset.messageBase = baseClass;
    element.className = `${baseClass} ${type}`;
    element.textContent = messageText(payload);
    messageTimers.set(element, window.setTimeout(() => {
        element.textContent = "";
        element.className = baseClass;
        messageTimers.delete(element);
    }, 3000));
}

function setMessage(id, payload, ok = true) {
    showMessage(byId(id), payload, ok ? "success" : "error");
}

function setResult(id, text, ok = true) {
    showMessage(byId(id), text, ok ? "success" : "error");
}

async function requestJson(url, options = {}) {
    const response = await fetch(url, {
        headers: { "Content-Type": "application/json" },
        ...options,
    });
    const contentType = response.headers.get("content-type") || "";
    const bodyText = await response.text();
    const bodyPreview = bodyText.slice(0, 200);
    console.log("[dashboard API]", {
        url,
        status: response.status,
        contentType,
        bodyPreview,
    });

    if (!contentType.includes("application/json")) {
        const error = `Expected JSON from ${url}, but received ${contentType || "unknown content-type"}`;
        console.error("[dashboard API] HTML/non-JSON response", {
            url,
            status: response.status,
            contentType,
            bodyPreview,
        });
        return {
            response,
            data: {
                error,
                details: bodyPreview,
            },
        };
    }

    let data = {};
    if (bodyText) {
        try {
            data = JSON.parse(bodyText);
        } catch (error) {
            console.error("[dashboard API] Invalid JSON response", {
                url,
                status: response.status,
                contentType,
                bodyPreview,
                error,
            });
            data = {
                error: `Invalid JSON from ${url}`,
                details: bodyPreview,
            };
        }
    }
    return { response, data };
}

function errorText(payload) {
    if (typeof payload === "string") {
        return payload;
    }
    if (!payload) {
        return "API request failed";
    }
    return payload.details
        ? `${payload.error || payload.message || "API request failed"} ${payload.details}`
        : payload.error || payload.message || JSON.stringify(payload);
}

function formData(form) {
    const data = Object.fromEntries(new FormData(form).entries());
    for (const key of ["user_id", "base_points", "max_points", "points_required", "active"]) {
        if (data[key] !== undefined && data[key] !== "") {
            data[key] = Number(data[key]);
        }
    }
    for (const key of ["amount", "multiplier"]) {
        if (data[key] !== undefined && data[key] !== "") {
            data[key] = Number(data[key]);
        }
    }
    return data;
}

function defaultValue(formId, fieldName) {
    const defaults = {
        "rule-form": {
            multiplier: "1",
            max_points: "100",
            active: "1",
        },
        "reward-form": {
            active: "1",
        },
    };
    return defaults[formId]?.[fieldName] || "";
}

function clearForm(formId) {
    const form = byId(formId);
    form.reset();
    const idInput = form.elements.id;
    if (idInput) {
        idInput.value = "";
    }
    Array.from(form.elements).forEach((field) => {
        if (!field.name || field.name === "id" || field.tagName === "BUTTON") {
            return;
        }
        if (field.tagName === "SELECT") {
            field.value = "1";
            return;
        }
        field.value = defaultValue(formId, field.name);
    });
    setFormMode(formId, false);
}

function showCreateForm(formId) {
    const form = byId(formId);
    clearForm(formId);
    form.hidden = false;
    form.classList.remove("hidden");
    form.classList.add("form-focus");
    form.scrollIntoView({ behavior: "smooth", block: "center" });

    const firstField = Array.from(form.elements).find((field) => {
        return field.name && field.name !== "id" && field.tagName !== "BUTTON";
    });
    if (firstField) {
        firstField.focus();
    }

    window.setTimeout(() => form.classList.remove("form-focus"), 900);
}

function cell(value) {
    return value === null || value === undefined || value === "" ? "-" : String(value);
}

function activeLabel(value) {
    return Number(value) === 1 ? "Active" : "Inactive";
}

function nextActiveValue(value) {
    return Number(value) === 1 ? 0 : 1;
}

function activeActionText(value) {
    return Number(value) === 1 ? "Make Inactive" : "Make Active";
}

function setFormMode(formId, isEdit) {
    const config = {
        "rule-form": {
            modeId: "rule-mode",
            submitId: "rule-submit",
            clearId: "rule-clear",
            createText: "Create New Rule",
            submitCreate: "Save Rule",
            submitUpdate: "Update Rule",
        },
        "reward-form": {
            modeId: "reward-mode",
            submitId: "reward-submit",
            clearId: "reward-clear",
            createText: "Create New Reward",
            submitCreate: "Save Reward",
            submitUpdate: "Update Reward",
        },
    }[formId];

    if (!config) {
        return;
    }

    byId(config.modeId).textContent = isEdit ? `Edit Mode: ${config.submitUpdate}` : config.createText;
    byId(config.submitId).textContent = isEdit ? config.submitUpdate : config.submitCreate;
    byId(config.clearId).textContent = "Cancel Edit";
    byId(config.clearId).classList.toggle("hidden", !isEdit);
}

function rowActions(editHandler, deleteHandler, toggleHandler, toggleText) {
    const wrap = document.createElement("div");
    wrap.className = "row-actions";

    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "secondary";
    edit.textContent = "Edit";
    edit.addEventListener("click", editHandler);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = "Delete";
    remove.addEventListener("click", deleteHandler);

    wrap.append(edit, remove);
    if (toggleHandler) {
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "secondary";
        toggle.textContent = toggleText;
        toggle.addEventListener("click", toggleHandler);
        wrap.appendChild(toggle);
    }
    return wrap;
}

function appendCells(row, values) {
    for (const value of values) {
        const td = document.createElement("td");
        td.textContent = cell(value);
        row.appendChild(td);
    }
}

function updateUserOptions() {
    const datalist = byId("user-id-options");
    if (!datalist) {
        return;
    }
    datalist.replaceChildren();
    for (const user of state.users) {
        const option = document.createElement("option");
        option.value = user.id;
        option.label = user.name ? `${user.name}${user.email ? ` (${user.email})` : ""}` : `User ${user.id}`;
        datalist.appendChild(option);
    }
}

function updateEventOptions() {
    const eventIdOptions = byId("event-id-options");
    const eventTypeOptions = byId("event-type-options");
    const eventTypes = new Set();

    if (eventIdOptions) {
        eventIdOptions.replaceChildren();
    }

    for (const rule of state.rules) {
        if (rule.event_type) {
            eventTypes.add(rule.event_type);
        }
        if (eventIdOptions && rule.event_id) {
            const option = document.createElement("option");
            option.value = rule.event_id;
            option.label = rule.event_type || "";
            eventIdOptions.appendChild(option);
        }
    }

    if (eventTypeOptions) {
        eventTypeOptions.replaceChildren();
        for (const eventType of Array.from(eventTypes).sort()) {
            const option = document.createElement("option");
            option.value = eventType;
            eventTypeOptions.appendChild(option);
        }
    }
}

function updateRelatedEventIds(eventType) {
    const eventIdOptions = byId("event-id-options");
    if (!eventIdOptions) {
        return;
    }
    const matchingRules = eventType
        ? state.rules.filter((rule) => rule.event_type === eventType)
        : state.rules;
    eventIdOptions.replaceChildren();
    for (const rule of matchingRules) {
        if (!rule.event_id) {
            continue;
        }
        const option = document.createElement("option");
        option.value = rule.event_id;
        option.label = rule.event_type || "";
        eventIdOptions.appendChild(option);
    }
}

async function loadUsers() {
    const { response, data } = await requestJson(api.users);
    if (!response.ok) {
        setMessage("users-message", data, false);
        return;
    }
    state.users = data.users || [];
    updateUserOptions();
    const tbody = byId("users-table");
    tbody.replaceChildren();

    for (const user of state.users) {
        const row = document.createElement("tr");
        appendCells(row, [user.id, user.name, user.email, user.created_at, activeLabel(user.active ?? 1)]);

        const actions = document.createElement("td");
        actions.appendChild(rowActions(
            () => {
                const form = byId("user-form");
                form.elements.id.value = user.id;
                form.elements.name.value = user.name || "";
                form.elements.email.value = user.email || "";
                form.scrollIntoView({ behavior: "smooth", block: "center" });
            },
            () => deleteRow(`${api.users}${user.id}/`, "users-message", loadUsers, row),
            () => toggleActive(`${api.users}${user.id}/`, nextActiveValue(user.active ?? 1), "users-message", loadUsers),
            activeActionText(user.active ?? 1)
        ));
        row.appendChild(actions);
        tbody.appendChild(row);
    }
}

async function loadRules() {
    const { response, data } = await requestJson(api.rules);
    if (!response.ok) {
        setMessage("rules-message", data, false);
        return;
    }
    state.rules = data.reward_rules || [];
    updateEventOptions();
    const tbody = byId("rules-table");
    tbody.replaceChildren();

    for (const rule of state.rules) {
        const row = document.createElement("tr");
        appendCells(row, [
            rule.id,
            rule.event_type,
            rule.base_points,
            rule.multiplier,
            rule.max_points,
            activeLabel(rule.active),
        ]);

        const actions = document.createElement("td");
        actions.appendChild(rowActions(
            () => {
                const form = byId("rule-form");
                form.elements.id.value = rule.id;
                form.elements.event_type.value = rule.event_type || "";
                form.elements.base_points.value = rule.base_points ?? "";
                form.elements.multiplier.value = rule.multiplier ?? 1;
                form.elements.max_points.value = rule.max_points ?? 100;
                form.elements.active.value = String(rule.active ?? 1);
                setFormMode("rule-form", true);
                form.scrollIntoView({ behavior: "smooth", block: "center" });
            },
            () => deleteRow(`${api.rules}${rule.id}/`, "rules-message", loadRules, row),
            () => toggleActive(`${api.rules}${rule.id}/`, nextActiveValue(rule.active), "rules-message", loadRules),
            activeActionText(rule.active)
        ));
        row.appendChild(actions);
        tbody.appendChild(row);
    }
}

async function loadRewards() {
    const { response, data } = await requestJson(`${api.rewards}?include_inactive=1`);
    if (!response.ok) {
        setMessage("rewards-message", data, false);
        return;
    }
    state.rewards = data.rewards || [];
    const tbody = byId("rewards-table");
    const datalist = byId("reward-code-options");
    tbody.replaceChildren();
    datalist.replaceChildren();

    for (const reward of state.rewards) {
        const option = document.createElement("option");
        option.value = reward.reward_code;
        datalist.appendChild(option);

        const row = document.createElement("tr");
        appendCells(row, [
            reward.id,
            reward.reward_code,
            reward.reward_name,
            reward.points_required,
            activeLabel(reward.active),
        ]);

        const actions = document.createElement("td");
        actions.appendChild(rowActions(
            () => {
                const form = byId("reward-form");
                form.elements.id.value = reward.id;
                form.elements.reward_code.value = reward.reward_code || "";
                form.elements.reward_name.value = reward.reward_name || "";
                form.elements.points_required.value = reward.points_required ?? "";
                form.elements.active.value = String(reward.active ?? 1);
                setFormMode("reward-form", true);
                form.scrollIntoView({ behavior: "smooth", block: "center" });
            },
            () => deleteRow(`${api.rewards}${reward.id}/`, "rewards-message", loadRewards, row),
            () => toggleActive(`${api.rewards}${reward.id}/`, nextActiveValue(reward.active), "rewards-message", loadRewards),
            activeActionText(reward.active)
        ));
        row.appendChild(actions);
        tbody.appendChild(row);
    }
}

async function saveResource(formId, baseUrl, messageId, reload) {
    const form = byId(formId);
    const data = formData(form);
    const id = data.id;
    delete data.id;
    if (formId === "reward-form") {
        data.code = data.reward_code;
        data.name = data.reward_name;
    }
    const url = id ? `${baseUrl}${id}/` : baseUrl;
    const method = id ? "PUT" : "POST";
    const body = JSON.stringify(data);
    let response;
    let payload;
    try {
        const result = await requestJson(url, { method, body });
        response = result.response;
        payload = result.data;
    } catch (error) {
        console.error("API request failed", { method, url, data, error });
        setMessage(messageId, error.message, false);
        return;
    }
    setMessage(messageId, payload, response.ok);
    if (!response.ok) {
        console.error("API request failed", {
            method,
            url,
            status: response.status,
            data,
            response: payload,
        });
        setMessage(messageId, errorText(payload), false);
        return;
    }
    if (response.ok) {
        clearForm(formId);
        await reload();
    }
}

async function deleteRow(url, messageId, reload, row) {
    const { response, data } = await requestJson(url, { method: "DELETE" });
    setMessage(messageId, data, response.ok);
    if (response.ok) {
        if (row) {
            row.remove();
        }
        await reload();
    }
}

async function toggleActive(url, active, messageId, reload) {
    const { response, data } = await requestJson(url, {
        method: "PATCH",
        body: JSON.stringify({ active }),
    });
    setMessage(messageId, data, response.ok);
    if (response.ok) {
        await reload();
    }
}

async function submitEvent(event) {
    event.preventDefault();
    const data = formData(event.currentTarget);
    const { response, data: payload } = await requestJson(api.events, {
        method: "POST",
        body: JSON.stringify(data),
    });
    setMessage("event-message", payload, response.ok);
    if (response.ok) {
        await loadUsers();
    }
}

async function autofillEventTypeForInput(input) {
    const form = input.form;
    const eventId = input.value.trim();
    if (!eventId) {
        return;
    }
    const rule = state.rules.find((item) => String(item.event_id) === eventId);
    if (!rule) {
        return;
    }
    if (input.value.trim() === eventId) {
        form.elements.event_type.value = rule.event_type || "";
    }
}

function autofillEventType(event) {
    window.clearTimeout(eventLookupTimer);
    autofillEventTypeForInput(event.currentTarget);
}

function queueAutofillEventType(event) {
    const input = event.currentTarget;
    window.clearTimeout(eventLookupTimer);
    eventLookupTimer = window.setTimeout(() => autofillEventTypeForInput(input), 300);
}

function updateEventIdSuggestions(event) {
    updateRelatedEventIds(event.currentTarget.value.trim());
}

async function loadBalance(form = byId("balance-form")) {
    const userId = form.elements.user_id.value;
    if (!userId) {
        setResult("balance-message", "Select a user ID first", false);
        return;
    }
    const { response, data } = await requestJson(`${api.balance}?user_id=${encodeURIComponent(userId)}`);
    if (response.ok) {
        setResult("balance-message", `User ${data.user_id} balance: ${data.balance}`, true);
    } else {
        setResult("balance-message", data.error || JSON.stringify(data), false);
    }
}

async function getBalance(event) {
    event.preventDefault();
    await loadBalance(event.currentTarget);
}

async function loadLedger(form = byId("ledger-form")) {
    const userId = form.elements.user_id.value;
    if (!userId) {
        setMessage("ledger-message", "Select a user ID first", false);
        return;
    }
    const { response, data } = await requestJson(`${api.ledger}?user_id=${encodeURIComponent(userId)}`);
    const tbody = byId("ledger-table");
    tbody.replaceChildren();

    if (!response.ok) {
        setMessage("ledger-message", data, false);
        return;
    }

    setMessage("ledger-message", `${data.ledger.length} ledger rows loaded`, true);
    for (const item of data.ledger) {
        const row = document.createElement("tr");
        appendCells(row, [
            item.id,
            item.event_id,
            item.points_earned,
            item.entry_type,
            item.description,
            item.created_at,
        ]);
        tbody.appendChild(row);
    }
}

async function getLedger(event) {
    event.preventDefault();
    await loadLedger(event.currentTarget);
}

async function redeem(event) {
    event.preventDefault();
    const data = formData(event.currentTarget);
    const { response, data: payload } = await requestJson(api.redeem, {
        method: "POST",
        body: JSON.stringify(data),
    });
    setMessage("redeem-message", payload, response.ok);
}

async function reverseEvent(event) {
    event.preventDefault();
    const eventId = event.currentTarget.elements.event_id.value;
    const { response, data } = await requestJson(`/api/events/${encodeURIComponent(eventId)}/reverse/`, {
        method: "POST",
        body: JSON.stringify({}),
    });
    setMessage("reverse-message", data, response.ok);
}

function bindForms() {
    byId("user-form").addEventListener("submit", (event) => {
        event.preventDefault();
        saveResource("user-form", api.users, "users-message", loadUsers);
    });
    byId("rule-form").addEventListener("submit", (event) => {
        event.preventDefault();
        saveResource("rule-form", api.rules, "rules-message", loadRules);
    });
    byId("reward-form").addEventListener("submit", (event) => {
        event.preventDefault();
        saveResource("reward-form", api.rewards, "rewards-message", loadRewards);
    });
    byId("event-form").addEventListener("submit", submitEvent);
    const eventIdInput = byId("event-form").elements.event_id;
    const eventTypeInput = byId("event-form").elements.event_type;
    eventIdInput.addEventListener("input", queueAutofillEventType);
    eventIdInput.addEventListener("change", autofillEventType);
    eventIdInput.addEventListener("blur", autofillEventType);
    eventTypeInput.addEventListener("input", updateEventIdSuggestions);
    eventTypeInput.addEventListener("change", updateEventIdSuggestions);
    byId("balance-form").addEventListener("submit", getBalance);
    byId("ledger-form").addEventListener("submit", getLedger);
    byId("redeem-form").addEventListener("submit", redeem);
    byId("reverse-form").addEventListener("submit", reverseEvent);

    document.querySelectorAll("[data-reset]").forEach((button) => {
        button.addEventListener("click", () => clearForm(button.dataset.reset));
    });
    byId("create-rule-button").addEventListener("click", () => showCreateForm("rule-form"));
    byId("create-reward-button").addEventListener("click", () => showCreateForm("reward-form"));
}

function setDefaultTimestamp() {
    const input = byId("event-form").elements.event_timestamp;
    const now = new Date();
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
    input.value = now.toISOString().slice(0, 16);
}

document.addEventListener("DOMContentLoaded", async () => {
    bindForms();
    setDefaultTimestamp();
    await Promise.all([loadUsers(), loadRules(), loadRewards()]);
});

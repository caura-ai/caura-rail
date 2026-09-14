const metaEl = document.getElementById("meta");
const turnsEl = document.getElementById("turns");
const messageEl = document.getElementById("message");
const agentEl = document.getElementById("agent");
const bootstrapBtn = document.getElementById("bootstrapBtn");
const cleanupBtn = document.getElementById("cleanupBtn");
const sendBtn = document.getElementById("sendBtn");

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    throw new Error(data.detail || data.error || `HTTP ${res.status}`);
  }
  return data;
}

function renderMeta(session) {
  const bits = [
    `backend=${session.backend}`,
    `llm=${session.llmMode}`,
    session.fleetId ? `fleet=${session.fleetId}` : "fleet=(none)",
    session.marker ? `marker=${session.marker}` : null,
  ].filter(Boolean);
  metaEl.textContent = bits.join(" · ");
}

function writeBadge(status) {
  const cls =
    status === "written" || status === "deduplicated"
      ? "ok"
      : status === "deferred"
        ? "warn"
        : "bad";
  return `<span class="badge ${cls}">${status}</span>`;
}

function renderTurn(turn, index) {
  const writes =
    turn.writes?.length > 0
      ? `<ul class="writes">${turn.writes
          .map(
            (w) => `<li>${writeBadge(w.status)}<div>
              <div>${w.id ? `<code>${w.id}</code>` : "<em>no id</em>"}</div>
              ${w.error ? `<div class="empty">${escapeHtml(w.error)}</div>` : ""}
            </div></li>`,
          )
          .join("")}</ul>`
      : `<p class="empty">No facts extracted this turn.</p>`;

  const degraded = turn.degraded
    ? `<span class="badge warn">degraded</span>`
    : `<span class="badge ok">clean</span>`;

  return `<article class="turn">
    <div class="turn-head">
      <span class="agent">#${index + 1} · ${escapeHtml(turn.agentId)}</span>
      ${degraded}
      <span class="badge">${escapeHtml(turn.llmMode || "?")}</span>
    </div>
    <div class="block">
      <p class="block-title">Customer / operator message</p>
      <pre>${escapeHtml(turn.message)}</pre>
    </div>
    <div class="block">
      <p class="block-title">Rail context (rules, then facts)</p>
      <pre>${escapeHtml(turn.context?.text || "(empty)")}</pre>
    </div>
    <div class="block">
      <p class="block-title">Assistant reply</p>
      <pre>${escapeHtml(turn.reply || "")}</pre>
    </div>
    <div class="block">
      <p class="block-title">Write results</p>
      ${writes}
    </div>
  </article>`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function renderTurns(turns) {
  if (!turns?.length) {
    turnsEl.innerHTML = `<p class="empty">No turns yet. Start a fleet, then send a message.</p>`;
    return;
  }
  turnsEl.innerHTML = turns.map((t, i) => renderTurn(t, i)).join("");
}

async function refresh() {
  const session = await api("/api/session");
  renderMeta(session);
  renderTurns(session.turns || []);
}

bootstrapBtn.addEventListener("click", async () => {
  bootstrapBtn.disabled = true;
  try {
    await api("/api/bootstrap", { method: "POST", body: "{}" });
    await refresh();
  } catch (err) {
    alert(err.message);
  } finally {
    bootstrapBtn.disabled = false;
  }
});

cleanupBtn.addEventListener("click", async () => {
  cleanupBtn.disabled = true;
  try {
    await api("/api/cleanup", { method: "POST", body: "{}" });
    await refresh();
  } catch (err) {
    alert(err.message);
  } finally {
    cleanupBtn.disabled = false;
  }
});

sendBtn.addEventListener("click", async () => {
  const message = messageEl.value.trim();
  if (!message) return;
  sendBtn.disabled = true;
  try {
    await api("/api/turn", {
      method: "POST",
      body: JSON.stringify({ agent: agentEl.value, message }),
    });
    messageEl.value = "";
    await refresh();
  } catch (err) {
    alert(err.message);
  } finally {
    sendBtn.disabled = false;
  }
});

refresh().catch((err) => {
  metaEl.textContent = `Failed to load session: ${err.message}`;
});

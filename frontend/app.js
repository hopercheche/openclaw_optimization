const state = {
  apiBase: localStorage.getItem("openclaw.apiBase") || "http://127.0.0.1:8787",
  activeRunId: null,
  events: [],
  source: null,
};

const els = {
  apiBase: document.querySelector("#apiBase"),
  healthStatus: document.querySelector("#healthStatus"),
  permissionMode: document.querySelector("#permissionMode"),
  goalInput: document.querySelector("#goalInput"),
  startRun: document.querySelector("#startRun"),
  refreshRuns: document.querySelector("#refreshRuns"),
  runList: document.querySelector("#runList"),
  activeRunTitle: document.querySelector("#activeRunTitle"),
  activeRunMeta: document.querySelector("#activeRunMeta"),
  eventCount: document.querySelector("#eventCount"),
  timeline: document.querySelector("#timeline"),
  loadAudit: document.querySelector("#loadAudit"),
  reconnectStream: document.querySelector("#reconnectStream"),
  auditState: document.querySelector("#auditState"),
  auditOutput: document.querySelector("#auditOutput"),
};

els.apiBase.value = state.apiBase;

function api(path) {
  return `${state.apiBase.replace(/\/$/, "")}${path}`;
}

function setHealth(ok, text) {
  els.healthStatus.className = `status-pill ${ok ? "ok" : "bad"}`;
  els.healthStatus.textContent = text;
}

async function request(path, options = {}) {
  const res = await fetch(api(path), {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `${res.status} ${res.statusText}`);
  }
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return res.json();
  }
  return res.text();
}

async function checkHealth() {
  try {
    const payload = await request("/api/health");
    const runtime = payload.as2?.runtime || "runtime";
    setHealth(true, runtime);
  } catch (error) {
    setHealth(false, "API offline");
  }
}

async function refreshRuns() {
  try {
    const payload = await request("/api/runs");
    renderRuns(payload.runs || []);
  } catch (error) {
    els.runList.innerHTML = `<div class="empty-state">API unavailable</div>`;
  }
}

function renderRuns(runs) {
  if (!runs.length) {
    els.runList.innerHTML = `<div class="empty-state">No runs yet</div>`;
    return;
  }

  els.runList.innerHTML = "";
  for (const run of runs) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = `run-item ${run.run_id === state.activeRunId ? "active" : ""}`;
    item.innerHTML = `
      <strong>${escapeHtml(run.run_id)}</strong>
      <span>${escapeHtml(trim(run.goal, 92))}</span>
      <div class="status-row">
        <span class="tag ${escapeHtml(run.status)}">${escapeHtml(run.status)}</span>
        <span class="tag">${escapeHtml(run.permission_mode)}</span>
        <span class="tag">${Number(run.event_count || 0)} events</span>
      </div>
    `;
    item.addEventListener("click", () => selectRun(run.run_id));
    els.runList.appendChild(item);
  }
}

async function selectRun(runId) {
  state.activeRunId = runId;
  els.loadAudit.disabled = false;
  els.reconnectStream.disabled = false;
  els.auditOutput.textContent = "";
  els.auditState.textContent = "Not loaded";

  const [runPayload, eventPayload] = await Promise.all([
    request(`/api/runs/${runId}`),
    request(`/api/runs/${runId}/events`),
  ]);
  renderActiveRun(runPayload.run);
  state.events = eventPayload.events || [];
  renderEvents();
  connectStream(runId, lastEventId());
  refreshRuns();
}

function renderActiveRun(run) {
  els.activeRunTitle.textContent = run.run_id;
  els.activeRunMeta.textContent = `${run.status} | ${run.permission_mode} | ${run.workspace_path}`;
}

function renderEvents() {
  els.eventCount.textContent = `${state.events.length} events`;
  if (!state.events.length) {
    els.timeline.innerHTML = `<div class="empty-state">Waiting for events</div>`;
    return;
  }

  els.timeline.innerHTML = "";
  for (const event of state.events) {
    const decision = event.data?.decision?.behavior || "";
    const node = document.createElement("article");
    node.className = `event ${event.event_type} ${decision}`;
    node.innerHTML = `
      <div class="event-head">
        <span class="tag ${escapeHtml(event.event_type)}">${escapeHtml(event.event_type)}</span>
        <span class="tag ${escapeHtml(decision)}">${escapeHtml(decision || `#${event.event_id}`)}</span>
      </div>
      <div class="event-message">${escapeHtml(event.message)}</div>
      ${event.data && Object.keys(event.data).length
        ? `<pre class="event-data">${escapeHtml(JSON.stringify(event.data, null, 2))}</pre>`
        : ""}
    `;
    els.timeline.appendChild(node);
  }
  els.timeline.scrollTop = els.timeline.scrollHeight;
}

async function startRun() {
  const goal = els.goalInput.value.trim();
  if (!goal) {
    els.goalInput.focus();
    return;
  }
  els.startRun.disabled = true;
  try {
    const payload = await request("/api/runs", {
      method: "POST",
      body: JSON.stringify({
        goal,
        permission_mode: els.permissionMode.value,
      }),
    });
    await selectRun(payload.run.run_id);
  } finally {
    els.startRun.disabled = false;
  }
}

function connectStream(runId, lastId = 0) {
  if (state.source) {
    state.source.close();
  }
  const source = new EventSource(api(`/api/runs/${runId}/stream?last_event_id=${lastId}`));
  state.source = source;

  source.onmessage = (message) => {
    addEvent(JSON.parse(message.data));
  };

  const eventTypes = [
    "run_started",
    "goal_analysis",
    "candidate_step",
    "planning",
    "reasoning",
    "permission",
    "tool_call",
    "tool_result",
    "critique",
    "human_gate",
    "final",
    "run_completed",
    "run_failed",
  ];

  for (const type of eventTypes) {
    source.addEventListener(type, (message) => {
      addEvent(JSON.parse(message.data));
      if (type === "run_completed" || type === "run_failed") {
        source.close();
        refreshRuns();
      }
    });
  }

  source.onerror = () => {
    source.close();
  };
}

function addEvent(event) {
  if (state.events.some((item) => item.event_id === event.event_id)) {
    return;
  }
  state.events.push(event);
  state.events.sort((a, b) => a.event_id - b.event_id);
  renderEvents();
}

function lastEventId() {
  return state.events.reduce((max, event) => Math.max(max, event.event_id), 0);
}

async function loadAudit() {
  if (!state.activeRunId) return;
  els.auditState.textContent = "Loading";
  try {
    const content = await request(`/api/runs/${state.activeRunId}/audit.md`);
    els.auditOutput.textContent = content;
    els.auditState.textContent = "Loaded";
  } catch (error) {
    els.auditState.textContent = "Not ready";
    els.auditOutput.textContent = String(error.message || error);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function trim(value, max) {
  if (!value || value.length <= max) return value || "";
  return `${value.slice(0, max - 1)}…`;
}

els.apiBase.addEventListener("change", () => {
  state.apiBase = els.apiBase.value.trim() || "http://127.0.0.1:8787";
  localStorage.setItem("openclaw.apiBase", state.apiBase);
  checkHealth();
  refreshRuns();
});

els.startRun.addEventListener("click", startRun);
els.refreshRuns.addEventListener("click", refreshRuns);
els.loadAudit.addEventListener("click", loadAudit);
els.reconnectStream.addEventListener("click", () => {
  if (state.activeRunId) connectStream(state.activeRunId, lastEventId());
});

checkHealth();
refreshRuns();

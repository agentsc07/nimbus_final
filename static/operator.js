/* Nimbus operator console (FR-22 view). Vanilla JS over the
   documented API only. Pause and cancel record the operator intent and
   publish a stop lease to robots via the cloud orchestrator (FR-22). */

const $ = (id) => document.getElementById(id);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* Authentication. The deployed cloud requires `Authorization: Bearer <operator token>` on every
   console call. Open /operator#token=<operator token> once (the fragment never reaches the
   server) or paste it into the banner; it is kept in sessionStorage for this tab only. */
const TOKEN_KEY = "nimbus.token.operator";
function readToken() { try { return sessionStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; } }
function saveToken(t) {
  try { if (t) sessionStorage.setItem(TOKEN_KEY, t); else sessionStorage.removeItem(TOKEN_KEY); } catch (e) { /* storage blocked */ }
}
(function takeTokenFromHash() {
  const m = location.hash.match(/(?:^#|&)token=([^&]+)/);
  if (m) {
    saveToken(decodeURIComponent(m[1]));
    history.replaceState(null, "", location.pathname + location.search);
  }
})();

function showAuthBanner(status) {
  if (document.getElementById("auth-banner")) return;
  const bar = document.createElement("div");
  bar.id = "auth-banner";
  bar.setAttribute("role", "alert");
  bar.style.cssText = "position:sticky;top:0;z-index:1000;background:#7a1f1f;color:#fff;padding:8px 12px;font:14px system-ui,sans-serif;display:flex;gap:8px;align-items:center;flex-wrap:wrap";
  const msg = document.createElement("span");
  msg.textContent = status === 403
    ? "This token is not allowed to do that (403)."
    : "This server requires an operator token (401). Paste it to continue:";
  const input = document.createElement("input");
  input.type = "password"; input.id = "auth-token-input"; input.placeholder = "operator token"; input.autocomplete = "off";
  const save = document.createElement("button");
  save.textContent = "Use token";
  save.onclick = () => { saveToken(input.value.trim()); location.reload(); };
  const clear = document.createElement("button");
  clear.textContent = "Clear token";
  clear.onclick = () => { saveToken(""); location.reload(); };
  bar.append(msg, input, save, clear);
  document.body.prepend(bar);
}

async function api(method, path, body) {
  const headers = { "Content-Type": "application/json" };
  const token = readToken();
  if (token) headers.Authorization = "Bearer " + token;
  const opts = { method, headers };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  let data = {};
  try { data = await res.json(); } catch (e) { data = {}; }
  if (res.status === 401 || res.status === 403) showAuthBanner(res.status);
  return { status: res.status, data };
}

/* The clarification question is an object {question, possible_readings}. */
function questionText(q) {
  if (!q) return "";
  if (typeof q === "string") return q;
  const readings = Array.isArray(q.possible_readings) && q.possible_readings.length
    ? ` (${q.possible_readings.join(" · ")})` : "";
  return (q.question || "") + readings;
}

const msgId = () => "op-" + Math.random().toString(36).slice(2, 12);
let selectedTaskId = null;


let demoTaskId = null;
const demoLoggedStages = new Set();

function formatTime(d = new Date()) {
  return d.toTimeString().split(" ")[0];
}

function appendDemoStream(stageKey, badgeClass, badgeLabel, detailText) {
  const stream = $("demo-progress-stream");
  if (!stream) return;
  if (stream.querySelector(".muted")) {
    stream.innerHTML = "";
  }
  const streamKey = `${demoTaskId}:${stageKey}`;
  if (demoLoggedStages.has(streamKey)) return;
  demoLoggedStages.add(streamKey);

  const row = document.createElement("div");
  row.className = "stream-entry";
  row.innerHTML = `<span class="stream-time">[${formatTime()}]</span>
    <span class="stream-badge ${badgeClass}">${esc(badgeLabel)}</span>
    <span class="stream-text">${esc(detailText)}</span>`;
  stream.appendChild(row);
  stream.scrollTop = stream.scrollHeight;
}

function setDemoProgressBar(stageName, details = {}) {
  const fill = $("demo-progress-fill");
  const s1 = $("step-received");
  const s2 = $("step-clarifying");
  const s3 = $("step-leased");
  const s4 = $("step-in-progress");
  const s5 = $("step-final");
  const finalLabel = $("step-final-label");
  if (!s1 || !s2 || !s3 || !s4 || !s5) return;

  [s1, s2, s3, s4, s5].forEach((s) => {
    s.className = "progress-step";
    const node = s.querySelector(".step-node");
    if (node) node.textContent = s.dataset.num;
  });
  if (finalLabel) finalLabel.textContent = "Completed / Blocked";

  if (stageName === "received") {
    if (fill) fill.style.width = "10%";
    s1.classList.add("active");
  } else if (stageName === "clarifying") {
    if (fill) fill.style.width = "30%";
    s1.classList.add("completed");
    s1.querySelector(".step-node").textContent = "✓";
    s2.classList.add("active");
  } else if (stageName === "leased") {
    if (fill) fill.style.width = "55%";
    s1.classList.add("completed");
    s1.querySelector(".step-node").textContent = "✓";
    if (details.clarified) {
      s2.classList.add("completed");
      s2.querySelector(".step-node").textContent = "✓";
    } else {
      s2.classList.add("skipped");
    }
    s3.classList.add("completed");
    s3.querySelector(".step-node").textContent = "✓";
    s4.classList.add("active");
  } else if (stageName === "in_progress") {
    if (fill) fill.style.width = "75%";
    s1.classList.add("completed");
    s1.querySelector(".step-node").textContent = "✓";
    if (details.clarified) {
      s2.classList.add("completed");
      s2.querySelector(".step-node").textContent = "✓";
    } else {
      s2.classList.add("skipped");
    }
    s3.classList.add("completed");
    s3.querySelector(".step-node").textContent = "✓";
    s4.classList.add("active");
  } else if (stageName === "completed") {
    if (fill) fill.style.width = "100%";
    s1.classList.add("completed");
    s1.querySelector(".step-node").textContent = "✓";
    if (details.clarified) {
      s2.classList.add("completed");
      s2.querySelector(".step-node").textContent = "✓";
    } else {
      s2.classList.add("skipped");
    }
    s3.classList.add("completed");
    s3.querySelector(".step-node").textContent = "✓";
    s4.classList.add("completed");
    s4.querySelector(".step-node").textContent = "✓";
    s5.classList.add("completed");
    s5.querySelector(".step-node").textContent = "✓";
    if (finalLabel) finalLabel.textContent = "Completed";
  } else if (["blocked", "cancelled", "rejected", "failed"].includes(stageName)) {
    if (fill) fill.style.width = "100%";
    s1.classList.add("completed");
    s1.querySelector(".step-node").textContent = "✓";
    s5.classList.add("blocked");
    s5.querySelector(".step-node").textContent = "✗";
    if (finalLabel) finalLabel.textContent = stageName === "blocked" ? "Blocked" : stageName.toUpperCase();
  }
}

function syncDemoTask(task) {
  if (!task) return;
  const status = task.status;
  const badge = $("demo-task-badge");
  if (badge) badge.textContent = `Task: ${task.task_id} [${status}]`;

  const clarifyBox = $("demo-clarify-box");
  const isClarified = demoLoggedStages.has(`${task.task_id}:clarified`);

  if (status === "received") {
    setDemoProgressBar("received");
    appendDemoStream("received", "received", "Request received", `Task ${task.task_id} logged in queue`);
  } else if (status === "needs_clarification") {
    setDemoProgressBar("clarifying");
    if (clarifyBox) {
      clarifyBox.style.display = "flex";
      $("demo-clarify-prompt").textContent = questionText(task.question) || "Clarification needed:";
    }
    appendDemoStream("clarifying", "clarifying", "Clarifying", questionText(task.question) || "Awaiting requester answer");
  } else {
    if (clarifyBox) clarifyBox.style.display = "none";
  }

  if (status === "leased") {
    const l = task.lease || {};
    setDemoProgressBar("leased", { clarified: isClarified });
    appendDemoStream("leased", "leased", "Leased", `Lease v${l.version || 1} issued to ${l.cluster_id || "fleet"} (priority: ${l.priority || "routine"})`);
    setDemoProgressBar("in_progress", { clarified: isClarified });
    appendDemoStream("in_progress", "in-progress", "In progress", "Dispatched to robot fleet, route executing");
  } else if (status === "in_progress" || status === "active") {
    setDemoProgressBar("in_progress", { clarified: isClarified });
    appendDemoStream("in_progress", "in-progress", "In progress", "Dispatched to robot fleet, route executing");
  } else if (status === "completed") {
    setDemoProgressBar("completed", { clarified: isClarified });
    appendDemoStream("completed", "completed", "Completed", "Delivery verified, task completed successfully");
  } else if (["blocked", "cancelled", "rejected", "failed"].includes(status)) {
    setDemoProgressBar(status);
    appendDemoStream(status, "blocked", status.toUpperCase(), task.reason || `Task transitioned to ${status}`);
  }
}

function setupDemoControls() {
  const input = $("demo-request-input");
  const submitBtn = $("demo-submit-btn");
  const clarifyBtn = $("demo-clarify-btn");
  const clarifyInput = $("demo-clarify-input");

  if (!submitBtn || !input) return;

  const doSubmit = async () => {
    const text = input.value.trim();
    if (!text) return;
    submitBtn.disabled = true;
    input.disabled = true;

    const stream = $("demo-progress-stream");
    if (stream) stream.innerHTML = "";
    demoTaskId = "submitting...";
    demoLoggedStages.clear();

    const badge = $("demo-task-badge");
    if (badge) badge.textContent = "Submitting request...";

    setDemoProgressBar("received");
    appendDemoStream("received", "received", "Request received", `"${text}"`);

    try {
      const { status, data } = await api("POST", "/requests", { text, message_id: msgId() });
      if (status === 201 && data && data.task_id) {
        demoTaskId = data.task_id;
        input.value = "";
        if (badge) badge.textContent = `Task: ${demoTaskId} [${data.status}]`;
        await refreshTasks();
        selectTask(demoTaskId);
      } else {
        alert(`Request failed: ${data.error || status}`);
        if (badge) badge.textContent = "Request failed";
        setDemoProgressBar("idle");
      }
    } catch (err) {
      console.error("Submit request error:", err);
      alert("Failed to submit request");
      if (badge) badge.textContent = "Error submitting";
      setDemoProgressBar("idle");
    } finally {
      submitBtn.disabled = false;
      input.disabled = false;
      input.focus();
    }
  };

  submitBtn.onclick = doSubmit;
  input.onkeydown = (e) => {
    if (e.key === "Enter") doSubmit();
  };

  if (clarifyBtn && clarifyInput) {
    const doClarify = async () => {
      const answer = clarifyInput.value.trim();
      if (!answer || !demoTaskId) return;
      clarifyBtn.disabled = true;
      try {
        const { status, data } = await api("POST", `/requests/${demoTaskId}/answer`, { text: answer, message_id: msgId() });
        if (status === 201) {
          appendDemoStream("clarified", "clarifying", "Clarifying", `Answered: "${answer}"`);
          clarifyInput.value = "";
          const clarifyBox = $("demo-clarify-box");
          if (clarifyBox) clarifyBox.style.display = "none";
          await refreshTasks();
        } else {
          alert(`Clarification failed: ${data.error || status}`);
        }
      } catch (err) {
        console.error("Clarification error:", err);
        alert("Failed to submit clarification");
      } finally {
        clarifyBtn.disabled = false;
      }
    };
    clarifyBtn.onclick = doClarify;
    clarifyInput.onkeydown = (e) => {
      if (e.key === "Enter") doClarify();
    };
  }
}

let _refreshTasksInProgress = false;
async function refreshTasks() {
  if (_refreshTasksInProgress) return;
  _refreshTasksInProgress = true;
  try {
    return await _doRefreshTasks();
  } finally {
    _refreshTasksInProgress = false;
  }
}
async function _doRefreshTasks() {
  refreshStock();
  const { status, data } = await api("GET", "/tasks");
  if (status !== 200 || !Array.isArray(data.tasks)) return;
  const rows = $("task-rows");
  rows.innerHTML = "";
  for (const t of data.tasks) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${esc(t.task_id)}</td>
      <td><span class="chip ${esc(t.status)}">${esc(t.status)}</span></td>
      <td>${esc(t.lease ? t.lease.priority : "-")}</td>
      <td>${esc(t.lease ? "v" + t.lease.version : "-")}</td>
      <td>${esc(t.lease ? t.lease.cluster_id : "-")}</td>`;
    if (t.task_id === selectedTaskId) tr.className = "active";
    tr.onclick = () => selectTask(t.task_id);
    rows.appendChild(tr);
  }
  if (window.NimbusSpatial && window.NimbusSpatial.onTasksUpdate) {
    window.NimbusSpatial.onTasksUpdate(data.tasks);
  }
  if (demoTaskId && data.tasks) {
    const active = data.tasks.find((t) => t.task_id === demoTaskId);
    if (active) syncDemoTask(active);
  }
}

function displayItemName(item) {
  if (item === "infusion_pump_paediatric") return "pediatric_infusion_pump";
  return item;
}

async function refreshStock() {
  const { status, data } = await api("GET", "/fleet");
  if (status !== 200 || !Array.isArray(data.fleet)) return;
  const clusters = data.fleet;
  const rawItems = [...new Set(clusters.flatMap((c) => Object.keys(c.stock)))];
  const itemsMap = new Map();
  for (const item of rawItems) {
    const display = displayItemName(item);
    if (!itemsMap.has(display)) {
      itemsMap.set(display, item);
    }
  }
  const displayItems = [...itemsMap.keys()].sort();
  $("stock-head").innerHTML = `<tr><th>item</th>${clusters.map((c) =>
    `<th>${esc(c.cluster_id)} <span class="muted">${esc(c.health)}</span></th>`).join("")}</tr>`;
  $("stock-rows").innerHTML = displayItems.map((display) => {
    const raw = itemsMap.get(display);
    return `<tr><td>${esc(display)}</td>${clusters.map((c) => `<td>${esc(c.stock[raw] ?? c.stock[display] ?? 0)}</td>`).join("")}</tr>`;
  }).join("");
}

async function selectTask(taskId) {
  selectedTaskId = taskId;
  demoTaskId = taskId;
  if (window.NimbusSpatial && window.NimbusSpatial.onTaskSelect) {
    window.NimbusSpatial.onTaskSelect(taskId);
  }
  await Promise.all([renderDetail(), refreshTasks()]);
}

async function renderDetail() {
  const box = $("detail");
  const id = selectedTaskId;   // responses for a task that is no longer selected are dropped, so the
  if (!id) {                   // panel (and its Pause/Cancel buttons) always belongs to the selected task
    box.innerHTML = `<p class="muted">Click a row to load its decision timeline.</p>`;
    return;
  }
  const { status, data: task } = await api("GET", `/tasks/${encodeURIComponent(id)}`);
  if (id !== selectedTaskId) return;
  if (status === 404) { box.innerHTML = `<p class="muted">Task not found.</p>`; return; }
  if (status !== 200) { box.innerHTML = `<p class="muted">Could not load the task (HTTP ${esc(status)}).</p>`; return; }

  const { data: tl } = await api("GET", `/tasks/${encodeURIComponent(id)}/timeline`);
  if (id !== selectedTaskId) return;
  box.innerHTML = `
    <h3>${esc(task.task_id)} <span class="chip ${esc(task.status)}">${esc(task.status)}</span></h3>
    <p class="muted">${esc(task.request_text)}</p>
    <p>
      <button id="pause-btn">Pause</button>
      <button id="cancel-btn">Cancel</button>
      <span class="muted">the cloud records the intent and publishes a stop lease; robot stop is confirmed by the edge, not shown here</span>
    </p>
    <h4>Decision timeline</h4>
    <ol class="timeline">${(tl.timeline || []).map((r) =>
      `<li><strong>${esc(r.who)}</strong>: ${esc((r.output && (r.output.event || r.output.decision)) || "?")}
       <span class="muted">${esc(r.timestamp)}</span></li>`).join("")}</ol>`;

  $("pause-btn").onclick = () => control("pause", task.task_id);
  $("cancel-btn").onclick = () => control("cancel", task.task_id);
}

async function control(action, taskId) {
  const target = taskId || selectedTaskId;
  if (!target) return;
  const cancelBtn = $("cancel-btn");
  const pauseBtn = $("pause-btn");
  if (action === "cancel" && cancelBtn) {
    cancelBtn.disabled = true;
    cancelBtn.textContent = "Cancelling...";
  } else if (action === "pause" && pauseBtn) {
    pauseBtn.disabled = true;
    pauseBtn.textContent = "Pausing...";
  }
  const { status, data } = await api(
    "POST", `/tasks/${encodeURIComponent(target)}/control`, { action, message_id: msgId() }
  );
  if (status !== 201) {
    alert(`Intent not recorded: ${data.error || status}`);
  }
  await renderDetail();
  await refreshTasks();
}

async function refreshFleet() {
  try {
    const { status, data } = await api("GET", "/fleet");
    if (status === 200 && window.NimbusSpatial && window.NimbusSpatial.updateFleet) {
      window.NimbusSpatial.updateFleet(data.fleet);
    }
  } catch (e) {
    // fleet query optional/graceful fallback
  }
}

async function refreshFault() {
  try {
    const { status, data } = await api("GET", "/fault");
    if (status === 200 && window.NimbusSpatial && window.NimbusSpatial.updateFault) {
      window.NimbusSpatial.updateFault(data);
    }
  } catch (e) {
    // fault query optional/graceful fallback
  }
}

async function updateLlmStatus() {
  const badge = $("llm-status-badge");
  if (!badge) return;

  try {
    const { status, data } = await api("GET", "/llm-status");
    if (status === 200 && data && data.status) {
      if (data.status === "live") {
        badge.textContent = "LLM: Bedrock (live)";
        badge.className = "llm-badge llm-live";
      } else if (data.status === "fallback") {
        badge.textContent = "LLM: rule fallback";
        badge.className = "llm-badge llm-fallback";
      } else {
        badge.textContent = "LLM: unknown";
        badge.className = "llm-badge llm-unknown";
      }
      return;
    }
  } catch (e) {
    // fallback to timeline inspection
  }

  try {
    const { status: tStatus, data: tData } = await api("GET", "/tasks");
    if (tStatus !== 200 || !tData.tasks || tData.tasks.length === 0) {
      badge.textContent = "LLM: unknown";
      badge.className = "llm-badge llm-unknown";
      return;
    }
    const tasks = tData.tasks;
    let latestLlm = null;
    for (let t = tasks.length - 1; t >= 0 && !latestLlm; t--) {
      const taskId = tasks[t].task_id;
      const { status: tlStatus, data: tlData } = await api("GET", `/tasks/${taskId}/timeline`);
      if (tlStatus !== 200 || !tlData.timeline) continue;
      for (let i = tlData.timeline.length - 1; i >= 0; i--) {
        const row = tlData.timeline[i];
        if (row.output && row.output.llm) {
          latestLlm = row.output.llm;
          break;
        }
      }
    }
    if (!latestLlm) {
      badge.textContent = "LLM: unknown";
      badge.className = "llm-badge llm-unknown";
    } else if (latestLlm.tokens_estimated === false && latestLlm.model) {
      badge.textContent = "LLM: Bedrock (live)";
      badge.className = "llm-badge llm-live";
    } else {
      badge.textContent = "LLM: rule fallback";
      badge.className = "llm-badge llm-fallback";
    }
  } catch (e) {
    badge.textContent = "LLM: unknown";
    badge.className = "llm-badge llm-unknown";
  }
}

function setupStockControls() {
  const setBtn = $("set-stock-btn");
  const resetBtn = $("reset-stock-btn");
  if (setBtn) {
    setBtn.onclick = async () => {
      const cluster = $("stock-cluster-select")?.value || "east-wing";
      const item = $("stock-item-select")?.value || "pediatric_infusion_pump";
      const qtyVal = $("stock-qty-input")?.value;
      const qty = parseInt(qtyVal, 10);
      if (isNaN(qty) || qty < 0) return;
      setBtn.disabled = true;
      try {
        await api("POST", "/fleet/stock", {
          cluster_id: cluster,
          stock: { [item]: qty }
        });
        await refreshStock();
        await refreshTasks();
      } catch (err) {
        console.error("Failed to set stock:", err);
      } finally {
        setBtn.disabled = false;
      }
    };
  }
  if (resetBtn) {
    resetBtn.onclick = async () => {
      const cluster = $("stock-cluster-select")?.value || "east-wing";
      const item = $("stock-item-select")?.value || "pediatric_infusion_pump";
      resetBtn.disabled = true;
      try {
        await api("POST", "/inventory/reset", {
          cluster_id: cluster,
          item: item
        });
        const qtyInput = $("stock-qty-input");
        if (qtyInput) qtyInput.value = "0";
        await refreshStock();
        await refreshTasks();
      } catch (err) {
        console.error("Failed to reset stock:", err);
      } finally {
        resetBtn.disabled = false;
      }
    };
  }
}

function setupMemoryControls() {
  const btn = $("reset-memory-btn");
  if (!btn) return;
  btn.onclick = async () => {
    btn.disabled = true;
    const prevText = btn.textContent;
    btn.textContent = "Resetting...";
    try {
      const { status, data } = await api("POST", "/reset-memory", {});
      if (status === 200 || status === 201) {
        btn.textContent = "Memory reset!";
        await refreshTasks();
        await refreshFleet();
        if (selectedTaskId) await renderDetail();
        setTimeout(() => {
          btn.textContent = prevText;
          btn.disabled = false;
        }, 1500);
      } else {
        alert(`Failed to reset memory: ${data.error || status}`);
        btn.textContent = prevText;
        btn.disabled = false;
      }
    } catch (err) {
      console.error("Failed to reset memory:", err);
      alert("Failed to reset request memory");
      btn.textContent = prevText;
      btn.disabled = false;
    }
  };
}

refreshTasks();
refreshFleet();
refreshFault();
updateLlmStatus();
setupStockControls();
setupMemoryControls();
setupDemoControls();
setInterval(() => {
  refreshTasks();
  refreshFleet();
  refreshFault();
}, 2000);
setInterval(updateLlmStatus, 5000);

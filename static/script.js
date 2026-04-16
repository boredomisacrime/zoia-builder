/* global mermaid, getProfile */

let referenceText = "";

/* ---------- Persistent patch state ---------- */

const STATE_KEY = "zoiaLastPatch";
const HISTORY_KEY = "zoiaHistory";
const MAX_HISTORY = 20;

let lastPatch = null;           // { filename, binBase64, notesText, aiJson, plan, planProse, description, mermaid, progressHtml, validation }
let pendingPlan = null;         // plan awaiting clarification
let pendingDescription = "";
let clarifyAnswers = {};

function persistState() {
  try {
    if (lastPatch) {
      sessionStorage.setItem(STATE_KEY, JSON.stringify(lastPatch));
    } else {
      sessionStorage.removeItem(STATE_KEY);
    }
  } catch (e) { /* quota */ }
}

function restoreState() {
  try {
    const raw = sessionStorage.getItem(STATE_KEY);
    if (!raw) return;
    lastPatch = JSON.parse(raw);
    if (lastPatch) {
      renderResult(lastPatch);
    }
  } catch (e) { /* ignore */ }
}

/* ---------- Utility ---------- */

function $(id) { return document.getElementById(id); }

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}

function markdownToHtml(md) {
  if (!md) return "";
  let html = md;
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    return `<pre><code>${escapeHtml(code.trim())}</code></pre>`;
  });
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
  html = html.replace(/^---$/gm, "<hr>");
  html = html.replace(/^[\-\*] (.+)$/gm, "<li>$1</li>");
  html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, "<ul>$1</ul>");
  html = html.replace(/^\d+\. (.+)$/gm, "<li>$1</li>");
  html = html.replace(/^\|(.+)\|$/gm, (match, row) => {
    const cells = row.split("|").map((c) => c.trim());
    if (cells.every((c) => /^[\-:]+$/.test(c))) return "";
    return "<tr>" + cells.map((c) => `<td>${c}</td>`).join("") + "</tr>";
  });
  html = html.replace(/((?:<tr>.*<\/tr>\n?)+)/g, "<table>$1</table>");
  html = html.replace(/^(?!<[a-z])((?!<).+)$/gm, "<p>$1</p>");
  html = html.replace(/<p>\s*<\/p>/g, "");
  return html;
}

function showError(msg) {
  const el = $("error");
  el.textContent = msg;
  el.style.display = "block";
}

function hideError() { $("error").style.display = "none"; }

/* ---------- PDF upload ---------- */

async function handlePdfUpload(input) {
  const file = input.files[0];
  if (!file) return;

  const statusEl = $("pdf-status");
  const filenameEl = $("pdf-filename");
  const labelEl = document.querySelector(".pdf-label");

  statusEl.style.display = "inline-flex";
  statusEl.classList.add("loading");
  filenameEl.textContent = `Uploading ${file.name}\u2026`;
  labelEl.style.display = "none";

  const form = new FormData();
  form.append("file", file);

  try {
    const resp = await fetch("/upload-pdf", { method: "POST", body: form });
    const data = await resp.json();

    if (!resp.ok) {
      statusEl.style.display = "none";
      labelEl.style.display = "inline-block";
      showError(data.error || "PDF upload failed.");
      input.value = "";
      return;
    }

    referenceText = data.text;
    filenameEl.textContent = `${file.name} (${data.pages} pages)`;
    statusEl.classList.remove("loading");
  } catch (err) {
    statusEl.style.display = "none";
    labelEl.style.display = "inline-block";
    showError("Could not upload PDF. Is the server running?");
    input.value = "";
  }
}

function removePdf() {
  referenceText = "";
  $("pdf-file").value = "";
  $("pdf-status").style.display = "none";
  document.querySelector(".pdf-label").style.display = "inline-block";
}

/* ---------- Main flow: design, clarify, build ---------- */

async function buildPatch() {
  const description = $("description").value.trim();
  if (!description) return;

  hideError();
  pendingDescription = description;
  clarifyAnswers = {};

  setBuildBusy(true, "Designing\u2026");

  const profile = (typeof getProfile === "function") ? getProfile() : null;

  try {
    const resp = await fetch("/design", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        description,
        reference_text: referenceText,
        profile: profile,
      }),
    });

    const data = await resp.json();
    if (!resp.ok) {
      showError(data.error || "Design failed.");
      return;
    }

    pendingPlan = data.plan;

    if (data.needs_clarification && data.questions && data.questions.length > 0) {
      showClarifyCard(data.plan_prose, data.questions);
      return;
    }

    // Confident enough — go straight to encoding the plan.
    await encodePlan(pendingPlan, description);
  } catch (err) {
    showError("Could not reach the server. Is it running?");
  } finally {
    setBuildBusy(false);
  }
}

function setBuildBusy(busy, label) {
  const btn = $("build-btn");
  const btnText = btn.querySelector(".btn-text");
  const btnLoading = btn.querySelector(".btn-loading");
  btn.disabled = busy;
  if (busy) {
    btnText.style.display = "none";
    btnLoading.textContent = label || "Working\u2026";
    btnLoading.style.display = "inline";
  } else {
    btnText.style.display = "inline";
    btnLoading.style.display = "none";
  }
}

/* ---------- Clarify card ---------- */

function showClarifyCard(planProse, questions) {
  $("clarify-plan-preview").textContent = planProse || "";
  const qEl = $("clarify-questions");
  qEl.innerHTML = "";
  questions.forEach((q) => {
    const row = document.createElement("div");
    row.className = "clarify-q";
    const label = document.createElement("div");
    label.className = "clarify-q-text";
    label.textContent = q.question;
    row.appendChild(label);

    if (q.options && q.options.length) {
      const opts = document.createElement("div");
      opts.className = "clarify-q-options";
      q.options.forEach((opt) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "clarify-chip";
        chip.textContent = opt;
        chip.onclick = () => {
          [...opts.children].forEach((c) => c.classList.remove("selected"));
          chip.classList.add("selected");
          clarifyAnswers[q.id] = opt;
        };
        opts.appendChild(chip);
      });
      row.appendChild(opts);
    } else {
      const input = document.createElement("input");
      input.type = "text";
      input.placeholder = "Your answer\u2026";
      input.oninput = () => { clarifyAnswers[q.id] = input.value.trim(); };
      row.appendChild(input);
    }

    qEl.appendChild(row);
  });

  $("clarify-card").style.display = "block";
  $("clarify-card").scrollIntoView({ behavior: "smooth", block: "start" });
}

function hideClarifyCard() {
  $("clarify-card").style.display = "none";
}

function cancelClarify() {
  hideClarifyCard();
  pendingPlan = null;
  clarifyAnswers = {};
}

async function submitClarifications() {
  if (!pendingPlan) return;
  hideClarifyCard();
  setBuildBusy(true, "Refining\u2026");

  const answerLines = [];
  const questions = pendingPlan.questions || [];
  questions.forEach((q) => {
    const a = clarifyAnswers[q.id];
    if (a && a.length) answerLines.push(`- ${q.question} -> ${a}`);
  });

  const description = pendingDescription + (answerLines.length
    ? "\n\nAnswers to clarifying questions:\n" + answerLines.join("\n")
    : "");

  const profile = (typeof getProfile === "function") ? getProfile() : null;

  try {
    // Redesign with the answers folded in
    const resp = await fetch("/design", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        description,
        reference_text: referenceText,
        profile,
        previous_plan: pendingPlan,
        tweak: answerLines.join("\n"),
      }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      showError(data.error || "Refine failed.");
      return;
    }
    pendingPlan = data.plan;
    await encodePlan(pendingPlan, description);
  } catch (e) {
    showError("Could not reach the server.");
  } finally {
    setBuildBusy(false);
  }
}

async function buildAnyway() {
  if (!pendingPlan) return;
  hideClarifyCard();
  setBuildBusy(true, "Building\u2026");
  try {
    await encodePlan(pendingPlan, pendingDescription);
  } finally {
    setBuildBusy(false);
  }
}

/* ---------- Stage 2: encode a plan via /build-bin SSE ---------- */

async function encodePlan(plan, description, opts = {}) {
  const profile = (typeof getProfile === "function") ? getProfile() : null;
  const autoRandomise = $("opt-randomise") && $("opt-randomise").checked;

  showResultSection();
  switchTab("progress");
  $("progress-panel").innerHTML = '<div class="progress-steps"><div class="progress-step active"><span class="streaming-cursor"></span> Preparing\u2026</div></div>';

  const body = {
    description: description,
    reference_text: referenceText,
    profile: profile,
    plan: plan,
    auto_randomise: autoRandomise || !!opts.autoRandomise,
  };

  try {
    const resp = await fetch("/build-bin", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      showError(data.error || "Failed to generate patch file.");
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let steps = [];
    let pendingEvent = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        const row = line.replace(/\r$/, "");
        if (row === "") continue;

        if (row.startsWith("event: ")) {
          pendingEvent = row.slice(7).trim();
        } else if (row.startsWith("data: ") && pendingEvent) {
          const data = JSON.parse(row.slice(6));

          if (pendingEvent === "progress") {
            steps.push(data.message);
            renderProgress(steps, true);
          } else if (pendingEvent === "done") {
            handleBinDone(data, steps, plan, description);
          } else if (pendingEvent === "error") {
            showError(data.message || "Unknown error from server.");
          }
          pendingEvent = null;
        }
      }
    }
  } catch (err) {
    showError("Could not connect to server. Is it running?");
  }
}

function renderProgress(steps, withCursor) {
  $("progress-panel").innerHTML = '<div class="progress-steps">' +
    steps.map((s, i) => {
      const isLast = i === steps.length - 1;
      const cls = isLast ? "active" : "done";
      const mark = isLast && withCursor ? '<span class="streaming-cursor"></span> ' : '&#10003; ';
      return `<div class="progress-step ${cls}">${mark}${escapeHtml(s)}</div>`;
    }).join("") + '</div>';
}

function handleBinDone(data, steps, plan, description) {
  const v = data.validation || {};
  if (v.passed) {
    steps.push(`Patch ready: ${data.modules} modules, ${data.connections} connections \u2014 validation PASSED \u2713`);
  } else {
    steps.push(`Patch ready: ${data.modules} modules, ${data.connections} connections`);
  }
  renderProgress(steps, false);

  if (v && !v.passed && v.issues && v.issues.length) {
    const warn = document.createElement("div");
    warn.className = "validation-warnings";
    warn.innerHTML = `<strong>\u26A0 Validation warnings (${v.attempts || 1} attempt${(v.attempts || 1) > 1 ? 's' : ''}):</strong><ul>` +
      v.issues.map((iss) => `<li>${escapeHtml(iss)}</li>`).join("") + "</ul>";
    $("progress-panel").appendChild(warn);
  }

  lastPatch = {
    filename: data.filename,
    binBase64: data.data,
    notesText: data.patch_text || "",
    aiJson: data.ai_json || null,
    plan: data.plan || plan || null,
    planProse: data.plan_prose || "",
    description: data.description || description || "",
    validation: v,
    progressHtml: $("progress-panel").innerHTML,
    createdAt: Date.now(),
  };
  persistState();
  saveToHistory(lastPatch);

  renderResult(lastPatch);
  triggerDownload(data.filename, data.data);
}

/* ---------- Rendering the result panel ---------- */

function showResultSection() {
  $("result-section").style.display = "block";
  $("result-section").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderResult(patch) {
  if (!patch) return;
  showResultSection();
  $("progress-panel").innerHTML = patch.progressHtml || "";
  $("notes-panel").innerHTML = markdownToHtml(patch.notesText || "") ||
    `<pre>${escapeHtml(patch.notesText || "")}</pre>`;
  $("plan-panel").innerHTML = patch.planProse
    ? `<pre>${escapeHtml(patch.planProse)}</pre>`
    : "<p>No saved design plan for this patch.</p>";
  $("json-panel").textContent = patch.aiJson ? JSON.stringify(patch.aiJson, null, 2) : "(no JSON)";

  renderDiagram(patch.plan);

  $("refine-section").style.display = "block";
}

function switchTab(tabId) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === tabId));
  document.querySelectorAll(".tab-body").forEach((b) => b.classList.toggle("active", b.id === `tab-${tabId}`));
  if (tabId === "diagram") {
    renderDiagram(lastPatch ? lastPatch.plan : null);
  }
}

let _mermaidReady = false;
function initMermaid() {
  if (_mermaidReady || typeof mermaid === "undefined") return;
  mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "strict", flowchart: { useMaxWidth: true } });
  _mermaidReady = true;
}

function planToMermaid(plan) {
  if (!plan || !plan.signal_flow || !plan.signal_flow.length) return "";
  const idMap = new Map();
  const lines = ["flowchart LR"];
  const edges = [];
  function idFor(label) {
    const key = label.trim();
    if (!idMap.has(key)) {
      const safe = key.replace(/[^A-Za-z0-9]/g, "") || `n${idMap.size}`;
      let unique = safe;
      let i = 1;
      const existing = new Set(idMap.values());
      while (existing.has(unique)) { i++; unique = `${safe}${i}`; }
      idMap.set(key, unique);
    }
    return idMap.get(key);
  }
  plan.signal_flow.forEach((raw) => {
    const s = String(raw).trim();
    const m = s.match(/^(.+?)\s*(?:->|→)\s*([^(]+?)(?:\s*\((.+)\))?$/);
    if (!m) return;
    const src = m[1].trim();
    const dst = m[2].trim();
    const label = (m[3] || "").trim();
    edges.push({ src, dst, label });
  });
  idMap.forEach((id, label) => {
    lines.push(`    ${id}["${label.replace(/"/g, "'")}"]`);
  });
  edges.forEach(({ src, dst, label }) => {
    const s = idFor(src);
    const d = idFor(dst);
    if (label) {
      lines.push(`    ${s} -->|"${label.replace(/[|"]/g, "'")}"| ${d}`);
    } else {
      lines.push(`    ${s} --> ${d}`);
    }
  });
  return lines.join("\n");
}

async function renderDiagram(plan) {
  const panel = $("diagram-panel");
  if (!panel) return;
  const src = planToMermaid(plan);
  if (!src) {
    panel.innerHTML = "<p>No signal flow available for this patch.</p>";
    return;
  }
  initMermaid();
  try {
    const { svg } = await mermaid.render("mermaid-diagram-" + Date.now(), src);
    panel.innerHTML = svg;
  } catch (e) {
    panel.innerHTML = `<pre>${escapeHtml(src)}</pre>`;
  }
}

/* ---------- Downloads ---------- */

function triggerDownload(filename, b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const blob = new Blob([bytes], { type: "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function downloadBinFromState() {
  if (!lastPatch) return;
  triggerDownload(lastPatch.filename, lastPatch.binBase64);
}

function downloadNotes() {
  if (!lastPatch) return;
  const blob = new Blob([lastPatch.notesText || ""], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = (lastPatch.filename || "patch").replace(".bin", "") + "_notes.txt";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function copyResult() {
  const text = (lastPatch && lastPatch.notesText) || $("notes-panel").innerText;
  navigator.clipboard.writeText(text).then(() => {
    const btn = document.querySelector('[onclick="copyResult()"]');
    if (!btn) return;
    const prev = btn.textContent;
    btn.textContent = "Copied!";
    setTimeout(() => { btn.textContent = prev; }, 1500);
  });
}

/* ---------- Refine ---------- */

async function refinePatch() {
  if (!lastPatch || !lastPatch.plan) { showError("No patch to refine."); return; }
  const tweak = $("refine-input").value.trim();
  if (!tweak) return;

  const btn = $("refine-btn");
  btn.disabled = true;
  const prevText = btn.textContent;
  btn.textContent = "Refining\u2026";
  hideError();

  const description = lastPatch.description || $("description").value.trim() || "Refined patch";
  const profile = (typeof getProfile === "function") ? getProfile() : null;

  try {
    const resp = await fetch("/design", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        description,
        reference_text: referenceText,
        profile,
        previous_plan: lastPatch.plan,
        tweak: tweak,
      }),
    });
    const data = await resp.json();
    if (!resp.ok) { showError(data.error || "Refine failed."); return; }

    $("refine-input").value = "";

    if (data.needs_clarification && data.questions && data.questions.length) {
      pendingPlan = data.plan;
      pendingDescription = description;
      showClarifyCard(data.plan_prose, data.questions);
      return;
    }

    await encodePlan(data.plan, description);
  } catch (e) {
    showError("Could not reach the server.");
  } finally {
    btn.disabled = false;
    btn.textContent = prevText;
  }
}

/* ---------- Suggestions ---------- */

async function loadSuggestions() {
  if (!lastPatch || !lastPatch.plan) return;
  const btn = $("suggest-btn");
  btn.disabled = true;
  const prev = btn.textContent;
  btn.textContent = "Thinking\u2026";

  try {
    const profile = (typeof getProfile === "function") ? getProfile() : null;
    const resp = await fetch("/suggest-improvements", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan: lastPatch.plan, profile }),
    });
    const data = await resp.json();
    if (!resp.ok) { showError(data.error || "Suggest failed."); return; }
    renderSuggestions(data.suggestions || []);
  } catch (e) {
    showError("Could not reach the server.");
  } finally {
    btn.disabled = false;
    btn.textContent = prev;
  }
}

function renderSuggestions(suggestions) {
  const panel = $("suggestions-panel");
  if (!suggestions.length) {
    panel.innerHTML = "<p>No suggestions right now.</p>";
    panel.style.display = "block";
    return;
  }
  panel.innerHTML = suggestions.map((s, i) => `
    <div class="suggestion-card" data-i="${i}">
      <div class="suggestion-title">${escapeHtml(s.title)}</div>
      <div class="suggestion-tweak">${escapeHtml(s.tweak)}</div>
    </div>
  `).join("");
  panel.style.display = "grid";
  panel.querySelectorAll(".suggestion-card").forEach((el, i) => {
    el.addEventListener("click", () => {
      $("refine-input").value = suggestions[i].tweak;
      refinePatch();
    });
  });
}

/* ---------- A/B variation ---------- */

async function variationAB() {
  if (!lastPatch || !lastPatch.plan) return;
  const btn = $("ab-btn");
  btn.disabled = true;
  const prev = btn.textContent;
  btn.textContent = "Generating\u2026";

  try {
    const tweaks = ["same concept, but lusher and more spacious", "same concept, but grittier and more aggressive"];
    const choice = tweaks[Math.floor(Math.random() * tweaks.length)];
    $("refine-input").value = choice;
    await refinePatch();
  } finally {
    btn.disabled = false;
    btn.textContent = prev;
  }
}

/* ---------- Clear ---------- */

function clearAll() {
  $("description").value = "";
  hideError();
  $("result-section").style.display = "none";
  $("refine-section").style.display = "none";
  hideClarifyCard();
  removePdf();
  lastPatch = null;
  pendingPlan = null;
  persistState();
  $("description").focus();
}

/* ---------- History ---------- */

function loadHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (e) { return []; }
}

function saveHistory(list) {
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, MAX_HISTORY))); } catch (e) { /* quota */ }
}

function saveToHistory(patch) {
  if (!patch) return;
  const list = loadHistory();
  const entry = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    filename: patch.filename,
    name: patch.plan && patch.plan.name ? patch.plan.name : (patch.filename || "patch").replace(".bin", ""),
    description: patch.description || "",
    createdAt: patch.createdAt || Date.now(),
    patch: patch,
  };
  list.unshift(entry);
  saveHistory(list);
  renderHistoryList();
}

function renderHistoryList() {
  const list = loadHistory();
  const el = $("history-list");
  if (!el) return;
  if (!list.length) {
    el.innerHTML = '<p style="color: var(--text-muted); font-size: 0.82rem;">No patches yet. Build one and it appears here.</p>';
    return;
  }
  el.innerHTML = list.map((h) => `
    <div class="history-item" data-id="${h.id}">
      <div class="history-item-name">${escapeHtml(h.name || "Patch")}</div>
      <div class="history-item-desc">${escapeHtml(h.description || "(no description)")}</div>
      <div class="history-item-date">${new Date(h.createdAt).toLocaleString()}</div>
    </div>
  `).join("");
  el.querySelectorAll(".history-item").forEach((row) => {
    row.addEventListener("click", () => {
      const id = row.dataset.id;
      const entry = loadHistory().find((e) => e.id === id);
      if (!entry) return;
      lastPatch = entry.patch;
      persistState();
      renderResult(lastPatch);
      toggleHistory();
    });
  });
}

function clearHistory() {
  if (!confirm("Clear patch history?")) return;
  saveHistory([]);
  renderHistoryList();
}

function toggleHistory() {
  const d = $("history-drawer");
  d.classList.toggle("open");
  if (d.classList.contains("open")) renderHistoryList();
}

/* ---------- Keyboard shortcut ---------- */

document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    const desc = $("description");
    if (document.activeElement === desc && desc.value.trim()) {
      buildPatch();
    }
  }
});

/* ---------- Init ---------- */

document.addEventListener("DOMContentLoaded", () => {
  restoreState();
  renderHistoryList();
});

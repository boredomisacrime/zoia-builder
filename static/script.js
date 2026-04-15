let referenceText = "";

async function handlePdfUpload(input) {
  const file = input.files[0];
  if (!file) return;

  const statusEl = document.getElementById("pdf-status");
  const filenameEl = document.getElementById("pdf-filename");
  const labelEl = document.querySelector(".pdf-label");

  statusEl.style.display = "inline-flex";
  statusEl.classList.add("loading");
  filenameEl.textContent = `Uploading ${file.name}…`;
  labelEl.style.display = "none";

  const form = new FormData();
  form.append("file", file);

  try {
    const resp = await fetch("/upload-pdf", { method: "POST", body: form });
    const data = await resp.json();

    if (!resp.ok) {
      statusEl.style.display = "none";
      labelEl.style.display = "inline-block";
      const errorEl = document.getElementById("error");
      errorEl.textContent = data.error || "PDF upload failed.";
      errorEl.style.display = "block";
      input.value = "";
      return;
    }

    referenceText = data.text;
    filenameEl.textContent = `${file.name} (${data.pages} pages)`;
    statusEl.classList.remove("loading");
  } catch (err) {
    statusEl.style.display = "none";
    labelEl.style.display = "inline-block";
    const errorEl = document.getElementById("error");
    errorEl.textContent = "Could not upload PDF. Is the server running?";
    errorEl.style.display = "block";
    input.value = "";
  }
}

function removePdf() {
  referenceText = "";
  document.getElementById("pdf-file").value = "";
  document.getElementById("pdf-status").style.display = "none";
  document.querySelector(".pdf-label").style.display = "inline-block";
}

async function buildPatch() {
  const description = document.getElementById("description").value.trim();
  if (!description) return;

  const btn = document.getElementById("build-btn");
  const btnText = btn.querySelector(".btn-text");
  const btnLoading = btn.querySelector(".btn-loading");
  const errorEl = document.getElementById("error");
  const resultSection = document.getElementById("result-section");
  const resultEl = document.getElementById("result");

  btn.disabled = true;
  btnText.style.display = "none";
  btnLoading.style.display = "inline";
  errorEl.style.display = "none";
  resultSection.style.display = "none";

  try {
    const resp = await fetch("/build", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description, reference_text: referenceText }),
    });

    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      errorEl.textContent = data.error || "Something went wrong.";
      errorEl.style.display = "block";
      return;
    }

    resultSection.style.display = "block";
    resultEl.innerHTML = '<span class="streaming-cursor"></span>';
    resultSection.scrollIntoView({ behavior: "smooth", block: "start" });

    let fullText = "";
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      fullText += decoder.decode(value, { stream: true });
      resultEl.innerHTML = markdownToHtml(fullText) + '<span class="streaming-cursor"></span>';
    }

    resultEl.innerHTML = markdownToHtml(fullText);
  } catch (err) {
    errorEl.textContent = "Could not connect to server. Is it running?";
    errorEl.style.display = "block";
  } finally {
    btn.disabled = false;
    btnText.style.display = "inline";
    btnLoading.style.display = "none";
  }
}

async function downloadBin() {
  const description = document.getElementById("description").value.trim();
  if (!description) return;

  const btn = document.getElementById("download-btn");
  const btnText = btn.querySelector(".btn-text");
  const btnLoading = btn.querySelector(".btn-loading");
  const errorEl = document.getElementById("error");
  const resultSection = document.getElementById("result-section");
  const resultEl = document.getElementById("result");

  btn.disabled = true;
  btnText.style.display = "none";
  btnLoading.style.display = "inline";
  errorEl.style.display = "none";

  resultSection.style.display = "block";
  resultEl.innerHTML = '<div class="progress-steps"><div class="progress-step active">Preparing...</div></div>';
  resultSection.scrollIntoView({ behavior: "smooth", block: "start" });

  try {
    const resp = await fetch("/build-bin", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description, reference_text: referenceText }),
    });

    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      errorEl.textContent = data.error || "Failed to generate patch file.";
      errorEl.style.display = "block";
      resultSection.style.display = "none";
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let steps = [];
    // Must persist across reader chunks: SSE may send "event: done" in one chunk
    // and a huge "data: {...}" line in the next. If we reset each read(), we
    // never handle the data line (UI stuck on "Encoding binary…").
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
            resultEl.innerHTML = '<div class="progress-steps">' +
              steps.map((s, i) => {
                const isLast = i === steps.length - 1;
                return `<div class="progress-step ${isLast ? 'active' : 'done'}">${isLast ? '<span class="streaming-cursor"></span> ' : '&#10003; '}${escapeHtml(s)}</div>`;
              }).join("") + '</div>';
          } else if (pendingEvent === "done") {
            const v = data.validation;
            if (v && v.passed) {
              steps.push(`Patch ready: ${data.modules} modules, ${data.connections} connections — validation PASSED ✓`);
            } else if (v && !v.passed) {
              steps.push(`Patch ready: ${data.modules} modules, ${data.connections} connections`);
            } else {
              steps.push(`Patch ready: ${data.modules} modules, ${data.connections} connections`);
            }

            let html = '<div class="progress-steps">' +
              steps.map(s => `<div class="progress-step done">&#10003; ${escapeHtml(s)}</div>`).join("");

            if (v && !v.passed && v.issues && v.issues.length) {
              html += '<div class="validation-warnings">';
              html += `<strong>⚠ Validation warnings (${v.attempts} attempt${v.attempts > 1 ? 's' : ''}):</strong><ul>`;
              for (const iss of v.issues) {
                html += `<li>${escapeHtml(iss)}</li>`;
              }
              html += '</ul></div>';
            }
            html += '</div>';
            resultEl.innerHTML = html;

            const binary = atob(data.data);
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
            const blob = new Blob([bytes], { type: "application/octet-stream" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = data.filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);

            if (data.patch_text) {
              setTimeout(() => {
                const txtBlob = new Blob([data.patch_text], { type: "text/plain" });
                const txtUrl = URL.createObjectURL(txtBlob);
                const txtA = document.createElement("a");
                txtA.href = txtUrl;
                txtA.download = data.filename.replace(".bin", ".txt");
                document.body.appendChild(txtA);
                txtA.click();
                txtA.remove();
                URL.revokeObjectURL(txtUrl);
              }, 500);
            }
          } else if (pendingEvent === "error") {
            errorEl.textContent = data.message;
            errorEl.style.display = "block";
            resultSection.style.display = "none";
          }
          pendingEvent = null;
        }
      }
    }
  } catch (err) {
    errorEl.textContent = "Could not connect to server. Is it running?";
    errorEl.style.display = "block";
    resultSection.style.display = "none";
  } finally {
    btn.disabled = false;
    btnText.style.display = "inline";
    btnLoading.style.display = "none";
  }
}

function clearAll() {
  document.getElementById("description").value = "";
  document.getElementById("error").style.display = "none";
  document.getElementById("result-section").style.display = "none";
  removePdf();
  document.getElementById("description").focus();
}

function copyResult() {
  const resultEl = document.getElementById("result");
  const text = resultEl.innerText;
  navigator.clipboard.writeText(text).then(() => {
    const btn = document.querySelector(".copy-btn");
    btn.textContent = "Copied!";
    setTimeout(() => { btn.textContent = "Copy"; }, 1500);
  });
}

document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    const desc = document.getElementById("description");
    if (document.activeElement === desc && desc.value.trim()) {
      buildPatch();
    }
  }
});

function markdownToHtml(md) {
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
    const tag = "td";
    return "<tr>" + cells.map((c) => `<${tag}>${c}</${tag}>`).join("") + "</tr>";
  });
  html = html.replace(/((?:<tr>.*<\/tr>\n?)+)/g, "<table>$1</table>");

  html = html.replace(/^(?!<[a-z])((?!<).+)$/gm, "<p>$1</p>");

  html = html.replace(/<p>\s*<\/p>/g, "");

  return html;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

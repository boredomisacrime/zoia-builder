(function () {
  const STORAGE_KEY = "zoiaProfile";
  const fields = [
    "artists",
    "genres",
    "instrument",
    "tuning",
    "playing_style",
    "rig",
    "stompswitch_comfort",
    "avoid",
  ];

  function $(id) { return document.getElementById(id); }

  function readFromForm() {
    const p = {
      artists: $("pf-artists").value.trim(),
      genres: $("pf-genres").value.trim(),
      instrument: $("pf-instrument").value.trim(),
      tuning: $("pf-tuning").value.trim(),
      playing_style: $("pf-playing").value.trim(),
      rig: $("pf-rig").value.trim(),
      expression_pedal: $("pf-expression").checked,
      midi: $("pf-midi").checked,
      wetness: parseInt($("pf-wetness").value, 10),
      stompswitch_comfort: $("pf-stompswitch").value.trim(),
      avoid: $("pf-avoid").value.trim(),
    };
    fields.forEach((k) => { if (p[k] === "") delete p[k]; });
    return p;
  }

  function writeToForm(p) {
    if (!p || typeof p !== "object") return;
    $("pf-artists").value = p.artists || "";
    $("pf-genres").value = p.genres || "";
    $("pf-instrument").value = p.instrument || "";
    $("pf-tuning").value = p.tuning || "";
    $("pf-playing").value = p.playing_style || "";
    $("pf-rig").value = p.rig || "";
    $("pf-expression").checked = !!p.expression_pedal;
    $("pf-midi").checked = !!p.midi;
    $("pf-wetness").value = p.wetness ?? 50;
    $("pf-wetness-val").textContent = `${p.wetness ?? 50}% wet`;
    $("pf-stompswitch").value = p.stompswitch_comfort || "";
    $("pf-avoid").value = p.avoid || "";
  }

  function loadLocal() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (e) {
      return null;
    }
  }

  function saveLocal(p) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
    } catch (e) { /* ignore */ }
  }

  function showStatus(msg, kind) {
    const el = $("pf-status");
    if (!el) return;
    el.textContent = msg;
    el.className = "drawer-status " + (kind || "");
    if (msg) setTimeout(() => { if (el.textContent === msg) el.textContent = ""; }, 4000);
  }

  window.getProfile = function () {
    const p = loadLocal();
    return p && Object.keys(p).length ? p : null;
  };

  window.saveProfile = function () {
    const p = readFromForm();
    saveLocal(p);
    showStatus("Saved to this browser.", "ok");
  };

  window.exportProfile = function () {
    const p = readFromForm();
    const blob = new Blob([JSON.stringify(p, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "zoia-profile.json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  window.importProfile = function (input) {
    const file = input.files && input.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = function (e) {
      try {
        const p = JSON.parse(e.target.result);
        writeToForm(p);
        saveLocal(p);
        showStatus("Imported.", "ok");
      } catch (err) {
        showStatus("Could not parse JSON.", "err");
      }
    };
    reader.readAsText(file);
    input.value = "";
  };

  window.saveProfileToDisk = async function () {
    const p = readFromForm();
    saveLocal(p);
    try {
      const resp = await fetch("/profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile: p }),
      });
      const data = await resp.json();
      if (resp.ok) {
        showStatus("Saved to disk.", "ok");
      } else {
        showStatus(data.error || "Could not save to disk.", "err");
      }
    } catch (e) {
      showStatus("Could not reach server.", "err");
    }
  };

  window.loadProfileFromDisk = async function () {
    try {
      const resp = await fetch("/profile");
      if (!resp.ok) return null;
      const data = await resp.json();
      return (data && data.profile && Object.keys(data.profile).length) ? data.profile : null;
    } catch (e) { return null; }
  };

  window.toggleProfile = function () {
    const d = $("profile-drawer");
    d.classList.toggle("open");
  };

  // Initialise form on load
  document.addEventListener("DOMContentLoaded", async function () {
    const wetness = $("pf-wetness");
    const wetVal = $("pf-wetness-val");
    if (wetness && wetVal) {
      wetness.addEventListener("input", () => { wetVal.textContent = `${wetness.value}% wet`; });
    }

    let profile = loadLocal();
    if (!profile) {
      profile = await window.loadProfileFromDisk();
      if (profile) saveLocal(profile);
    }
    if (profile) writeToForm(profile);
  });
})();

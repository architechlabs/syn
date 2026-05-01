"""Ingress-safe web UI for the Syn add-on."""

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Syn</title>
  <style>
    :root {
      color-scheme: dark;
      --ink: #f7efe0;
      --muted: #aeb9b8;
      --line: rgba(255,255,255,.14);
      --panel: rgba(18,28,30,.76);
      --panel2: rgba(255,255,255,.08);
      --gold: #e8b65b;
      --mint: #7be0c3;
      --bad: #ff8d8d;
      --good: #9df0b0;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      font-family: "Trebuchet MS", Verdana, sans-serif;
      background:
        radial-gradient(circle at top left, rgba(232,182,91,.26), transparent 30rem),
        radial-gradient(circle at bottom right, rgba(123,224,195,.18), transparent 28rem),
        linear-gradient(135deg, #0f1719, #203034 54%, #111819);
    }
    main { width: min(1240px, calc(100% - 24px)); margin: 0 auto; padding: 22px 0; }
    header {
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: end;
      margin-bottom: 16px;
    }
    h1 { margin: 0; font: 800 clamp(2.4rem, 8vw, 5rem)/.9 Georgia, serif; letter-spacing: -.08em; }
    .tagline { margin: 8px 0 0; color: var(--muted); max-width: 680px; }
    .pill {
      display: inline-flex;
      gap: 8px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 8px 12px;
      color: var(--muted);
      background: rgba(0,0,0,.18);
      font-size: .86rem;
      white-space: nowrap;
    }
    .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--bad); }
    .dot.ok { background: var(--good); }
    .grid { display: grid; grid-template-columns: minmax(0, .95fr) minmax(380px, 1.05fr); gap: 16px; }
    .card {
      border: 1px solid var(--line);
      border-radius: 24px;
      background: var(--panel);
      box-shadow: 0 22px 70px rgba(0,0,0,.28);
      backdrop-filter: blur(18px);
      overflow: hidden;
    }
    .section { padding: 18px; border-bottom: 1px solid var(--line); }
    .section:last-child { border-bottom: 0; }
    h2 { margin: 0 0 12px; font-size: .9rem; letter-spacing: .12em; text-transform: uppercase; color: var(--mint); }
    label { display: block; margin: 12px 0 7px; color: var(--muted); font-size: .82rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
    input, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 16px;
      color: var(--ink);
      background: rgba(0,0,0,.24);
      padding: 13px 14px;
      outline: none;
      font: 1rem/1.4 "Trebuchet MS", Verdana, sans-serif;
    }
    textarea { min-height: 92px; resize: vertical; }
    input:focus, textarea:focus { border-color: var(--gold); box-shadow: 0 0 0 3px rgba(232,182,91,.16); }
    .row { display: grid; grid-template-columns: 1fr auto; gap: 10px; align-items: end; }
    .actions { display: flex; flex-wrap: wrap; gap: 10px; }
    button, a.button {
      border: 0;
      border-radius: 999px;
      color: #172022;
      background: var(--gold);
      cursor: pointer;
      font: 800 .9rem "Trebuchet MS", Verdana, sans-serif;
      padding: 11px 15px;
      text-decoration: none;
    }
    button.secondary, a.button.secondary { color: var(--ink); background: var(--panel2); border: 1px solid var(--line); }
    button.ghost { color: var(--muted); background: transparent; border: 1px solid var(--line); }
    button:disabled { cursor: not-allowed; opacity: .58; }
    .chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
    .chip { padding: 8px 10px; border-radius: 999px; border: 1px solid var(--line); background: rgba(0,0,0,.18); color: var(--muted); cursor: pointer; }
    .chip.active { background: rgba(232,182,91,.18); color: var(--ink); border-color: rgba(232,182,91,.58); }
    .entity-toolbar { display: grid; grid-template-columns: 1fr auto auto; gap: 8px; margin-bottom: 10px; }
    .entities { display: grid; gap: 8px; max-height: 460px; overflow: auto; padding-right: 4px; }
    .entity {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 10px;
      align-items: start;
      padding: 11px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(0,0,0,.16);
    }
    .entity strong { display: block; font-size: .95rem; }
    .entity small { display: block; color: var(--muted); margin-top: 4px; overflow-wrap: anywhere; }
    .status {
      color: var(--muted);
      min-height: 24px;
      margin-top: 12px;
      font-size: .92rem;
    }
    .status.ok { color: var(--good); }
    .status.bad { color: var(--bad); }
    .summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
    .metric { padding: 12px; border-radius: 16px; background: rgba(0,0,0,.18); border: 1px solid var(--line); }
    .metric b { display: block; font-size: 1.25rem; color: var(--ink); }
    .metric span { color: var(--muted); font-size: .78rem; text-transform: uppercase; letter-spacing: .08em; }
    pre {
      margin: 0;
      min-height: 380px;
      max-height: 620px;
      overflow: auto;
      white-space: pre-wrap;
      color: #eefcf7;
      font: .9rem/1.55 Consolas, "Courier New", monospace;
    }
    .empty {
      padding: 18px;
      border: 1px dashed rgba(255,255,255,.22);
      border-radius: 16px;
      color: var(--muted);
      background: rgba(0,0,0,.14);
    }
    @media (max-width: 900px) {
      header { align-items: start; flex-direction: column; }
      .grid { grid-template-columns: 1fr; }
      .entity-toolbar { grid-template-columns: 1fr; }
      .summary { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Syn</h1>
        <p class="tagline">Scene building without YAML. Pick devices, describe the vibe, preview the plan, then save it.</p>
      </div>
      <div class="pill"><span id="health-dot" class="dot"></span><span id="health-text">Checking...</span></div>
    </header>

    <div class="grid">
      <section class="card">
        <div class="section">
          <h2>Scene</h2>
          <label for="prompt">Prompt</label>
          <textarea id="prompt">Create a cozy movie night scene</textarea>
          <div class="row">
            <div>
              <label for="room">Area or search term</label>
              <input id="room" list="areas" placeholder="bedroom, living, tv, lamp">
              <datalist id="areas"></datalist>
            </div>
            <button class="secondary" id="clear-room">All devices</button>
          </div>
          <div class="actions" style="margin-top:14px">
            <button id="preview">Preview</button>
            <button class="secondary" id="apply">Apply preview</button>
            <button id="generate">Save draft</button>
            <button class="secondary" id="refresh">Refresh devices</button>
          </div>
          <div id="status" class="status">Ready.</div>
        </div>

        <div class="section">
          <h2>Devices</h2>
          <div class="entity-toolbar">
            <input id="search" placeholder="Filter by name, entity id, capability">
            <button class="ghost" id="select-all">Select all</button>
            <button class="ghost" id="select-none">Clear</button>
          </div>
          <div id="chips" class="chips"></div>
          <div id="entities" class="entities" style="margin-top:12px">
            <div class="empty">Loading controllable Home Assistant entities...</div>
          </div>
        </div>
      </section>

      <aside class="card">
        <div class="section">
          <h2>Health</h2>
          <div class="summary">
            <div class="metric"><b id="metric-entities">0</b><span>entities</span></div>
            <div class="metric"><b id="metric-selected">0</b><span>selected</span></div>
            <div class="metric"><b id="metric-areas">0</b><span>areas</span></div>
          </div>
          <div class="actions" style="margin-top:12px">
            <button class="secondary" id="config">Config</button>
            <button class="secondary" id="diagnostics">Diagnostics</button>
            <a class="button secondary" id="docs" href="docs">API docs</a>
          </div>
        </div>
        <div class="section">
          <h2>Output</h2>
          <pre id="output">Preview output will appear here.</pre>
        </div>
      </aside>
    </div>
  </main>

  <script>
    const $ = (selector) => document.querySelector(selector);
    const statusEl = $("#status");
    const outputEl = $("#output");
    const base = window.location.pathname.endsWith("/") ? window.location.pathname : `${window.location.pathname}/`;
    const state = {entities: [], domain: "all", areas: [], lastScene: null};
    $("#docs").href = `${base}docs`;

    const endpoint = (path) => `${base}${path}`;

    function setStatus(message, kind = "") {
      statusEl.className = `status ${kind}`;
      statusEl.textContent = message;
    }

    function selectedEntities() {
      return [...document.querySelectorAll("[data-entity]:checked")]
        .map((box) => state.entities.find((entity) => entity.entity_id === box.value))
        .filter(Boolean);
    }

    function filteredEntities() {
      const text = $("#search").value.trim().toLowerCase();
      return state.entities.filter((entity) => {
        if (state.domain !== "all" && entity.domain !== state.domain) return false;
        if (!text) return true;
        const haystack = [
          entity.entity_id,
          entity.name,
          entity.room,
          entity.domain,
          ...(entity.capabilities || [])
        ].join(" ").toLowerCase();
        return haystack.includes(text);
      });
    }

    function renderChips() {
      const domains = ["all", ...new Set(state.entities.map((entity) => entity.domain).sort())];
      $("#chips").innerHTML = domains.map((domain) =>
        `<button class="chip ${domain === state.domain ? "active" : ""}" data-domain="${domain}">${domain}</button>`
      ).join("");
      document.querySelectorAll("[data-domain]").forEach((button) => {
        button.addEventListener("click", () => {
          state.domain = button.dataset.domain;
          render();
        });
      });
    }

    function render() {
      const entities = filteredEntities();
      $("#metric-entities").textContent = state.entities.length;
      $("#metric-selected").textContent = selectedEntities().length;
      $("#metric-areas").textContent = state.areas.length;
      renderChips();
      if (!entities.length) {
        $("#entities").innerHTML = `<div class="empty">No matching controllable devices. Clear the area/filter or assign devices to an Area in Home Assistant.</div>`;
        return;
      }
      $("#entities").innerHTML = entities.map((entity) => `
        <label class="entity">
          <input type="checkbox" data-entity checked value="${entity.entity_id}">
          <span>
            <strong>${entity.name || entity.entity_id}</strong>
            <small>${entity.entity_id}</small>
            <small>${entity.domain} | ${(entity.capabilities || []).join(", ") || "on_off"}${entity.room ? ` | ${entity.room}` : ""}</small>
          </span>
        </label>
      `).join("");
      document.querySelectorAll("[data-entity]").forEach((box) => box.addEventListener("change", renderMetrics));
      renderMetrics();
    }

    function renderMetrics() {
      $("#metric-selected").textContent = selectedEntities().length;
    }

    async function getJson(path) {
      const response = await fetch(endpoint(path));
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail?.message || data.detail || `HTTP ${response.status}`);
      return data;
    }

    async function loadAreas() {
      try {
        const data = await getJson("areas");
        state.areas = data.areas || [];
        $("#areas").innerHTML = state.areas.map((area) => `<option value="${area.area_id}">${area.name}</option>`).join("");
      } catch {
        state.areas = [];
      }
      $("#metric-areas").textContent = state.areas.length;
    }

    async function loadEntities() {
      setStatus("Fetching devices...");
      const room = $("#room").value.trim();
      const query = room ? `?room_id=${encodeURIComponent(room)}` : "";
      try {
        const data = await getJson(`entities${query}`);
        state.entities = data.entities || [];
        if (!state.entities.length && room) {
          setStatus(`No devices matched "${room}". Showing all devices so you can choose manually.`, "bad");
          const fallback = await getJson("entities");
          state.entities = fallback.entities || [];
        } else {
          setStatus(`Loaded ${state.entities.length} controllable devices.`, state.entities.length ? "ok" : "bad");
        }
        render();
      } catch (error) {
        state.entities = [];
        render();
        setStatus(`Device discovery failed: ${error.message}`, "bad");
      }
    }

    function buildPayload() {
      const entities = selectedEntities();
      return {
        user_prompt: $("#prompt").value.trim(),
        room_id: $("#room").value.trim() || null,
        entities
      };
    }

    async function send(path, label) {
      const payload = buildPayload();
      if (!payload.entities.length) {
        setStatus("Select at least one device before previewing.", "bad");
        return;
      }
      setStatus(`${label}...`);
      document.querySelectorAll("button").forEach((button) => button.disabled = true);
      try {
        const response = await fetch(endpoint(path), {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload)
        });
        const data = await response.json();
        outputEl.textContent = JSON.stringify(data, null, 2);
        if (!response.ok) throw new Error(data.detail?.message || data.detail || data.errors || `HTTP ${response.status}`);
        state.lastScene = data.scene || null;
        setStatus("Scene response received.", "ok");
      } catch (error) {
        setStatus(error.message, "bad");
      } finally {
        document.querySelectorAll("button").forEach((button) => button.disabled = false);
      }
    }

    async function showConfig() {
      const data = await getJson("config_status");
      outputEl.textContent = JSON.stringify(data, null, 2);
      setStatus(data.api_key_configured ? "AI key configured." : "AI key missing.", data.api_key_configured ? "ok" : "bad");
    }

    async function showDiagnostics() {
      const data = await getJson("discovery_status");
      outputEl.textContent = JSON.stringify(data, null, 2);
      $("#health-dot").classList.toggle("ok", Boolean(data.ok));
      $("#health-text").textContent = data.ok ? "Discovery healthy" : "Discovery issue";
      setStatus(data.message, data.ok ? "ok" : "bad");
    }

    async function applyPreview() {
      if (!state.lastScene) {
        setStatus("Preview a scene first, then apply it.", "bad");
        return;
      }
      setStatus("Applying scene...");
      try {
        const response = await fetch(endpoint("execute_scene"), {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({scene: state.lastScene})
        });
        const data = await response.json();
        outputEl.textContent = JSON.stringify(data, null, 2);
        if (!response.ok || data.overall_status === "failed") throw new Error(data.message || "One or more actions failed.");
        setStatus(`Applied ${data.actions_executed || 0} actions.`, "ok");
      } catch (error) {
        setStatus(error.message, "bad");
      }
    }

    $("#preview").addEventListener("click", () => send("preview_scene", "Previewing"));
    $("#apply").addEventListener("click", applyPreview);
    $("#generate").addEventListener("click", () => send("generate_scene", "Saving draft"));
    $("#refresh").addEventListener("click", loadEntities);
    $("#clear-room").addEventListener("click", () => { $("#room").value = ""; loadEntities(); });
    $("#room").addEventListener("change", loadEntities);
    $("#search").addEventListener("input", render);
    $("#select-all").addEventListener("click", () => { document.querySelectorAll("[data-entity]").forEach((box) => box.checked = true); renderMetrics(); });
    $("#select-none").addEventListener("click", () => { document.querySelectorAll("[data-entity]").forEach((box) => box.checked = false); renderMetrics(); });
    $("#config").addEventListener("click", showConfig);
    $("#diagnostics").addEventListener("click", showDiagnostics);

    loadAreas();
    loadEntities();
    showDiagnostics();
  </script>
</body>
</html>
"""

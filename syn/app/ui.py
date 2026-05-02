"""Ingress-safe responsive web UI for the Syn add-on."""

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Syn</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #07110f;
      --ink: #f4efe5;
      --muted: #9baaa5;
      --soft: rgba(244,239,229,.08);
      --panel: rgba(12,26,23,.82);
      --panel-strong: rgba(15,36,32,.96);
      --line: rgba(244,239,229,.14);
      --accent: #f0b95a;
      --accent-2: #55d6b0;
      --danger: #ff8a7a;
      --ok: #8cf2ae;
      --shadow: 0 22px 70px rgba(0,0,0,.38);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      font-family: "Segoe UI", "Aptos", sans-serif;
      background:
        radial-gradient(circle at 12% 10%, rgba(240,185,90,.26), transparent 30rem),
        radial-gradient(circle at 92% 18%, rgba(85,214,176,.2), transparent 26rem),
        radial-gradient(circle at 50% 110%, rgba(240,185,90,.15), transparent 30rem),
        linear-gradient(135deg, #07110f 0%, #13231f 50%, #07110f 100%);
    }
    button, input, textarea { font: inherit; }
    button {
      border: 0;
      border-radius: 999px;
      padding: 12px 16px;
      color: #10211d;
      background: var(--accent);
      font-weight: 800;
      cursor: pointer;
      box-shadow: 0 10px 24px rgba(240,185,90,.18);
    }
    button.secondary { color: var(--ink); background: var(--soft); border: 1px solid var(--line); box-shadow: none; }
    button.ghost { color: var(--muted); background: transparent; border: 1px solid var(--line); box-shadow: none; }
    button:disabled { opacity: .55; cursor: not-allowed; }
    main { width: min(1440px, calc(100% - 28px)); margin: 0 auto; padding: 28px 0; }
    .hero {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 18px;
      align-items: end;
      margin-bottom: 18px;
    }
    h1 { margin: 0; font: 900 clamp(3rem, 8vw, 6.5rem)/.82 Georgia, serif; letter-spacing: -.08em; }
    .lede { max-width: 720px; margin: 12px 0 0; color: var(--muted); font-size: 1.02rem; }
    .health {
      min-width: 260px;
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 14px;
      background: rgba(0,0,0,.22);
      box-shadow: var(--shadow);
    }
    .health strong { display: block; margin-bottom: 4px; }
    .health span { color: var(--muted); font-size: .9rem; }
    .dot { display:inline-block; width: 10px; height: 10px; margin-right: 8px; border-radius: 50%; background: var(--danger); }
    .dot.ok { background: var(--ok); }
    .layout { display: grid; grid-template-columns: 390px minmax(0, 1fr) 390px; gap: 16px; align-items: start; }
    .card {
      border: 1px solid var(--line);
      border-radius: 28px;
      background: var(--panel);
      box-shadow: var(--shadow);
      backdrop-filter: blur(18px);
      overflow: hidden;
    }
    .card-header { padding: 18px 18px 0; }
    .card-body { padding: 18px; }
    .card + .card { margin-top: 16px; }
    h2 { margin: 0; font-size: .84rem; letter-spacing: .14em; text-transform: uppercase; color: var(--accent-2); }
    .hint { margin: 8px 0 0; color: var(--muted); font-size: .9rem; }
    label { display:block; margin: 14px 0 7px; color: var(--muted); font-size: .78rem; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; }
    input, textarea {
      width: 100%;
      color: var(--ink);
      background: rgba(0,0,0,.24);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 13px 14px;
      outline: none;
    }
    textarea { min-height: 126px; resize: vertical; line-height: 1.5; }
    input:focus, textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 4px rgba(240,185,90,.14); }
    .stack { display: grid; gap: 10px; }
    .split { display: grid; grid-template-columns: 1fr auto; gap: 10px; align-items: end; }
    .actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }
    .metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
    .metric { border: 1px solid var(--line); border-radius: 18px; padding: 13px; background: rgba(0,0,0,.18); }
    .metric b { display:block; font-size: 1.45rem; }
    .metric span { color: var(--muted); font-size: .76rem; text-transform: uppercase; letter-spacing: .08em; }
    .toolbar { display: grid; grid-template-columns: 1fr auto auto; gap: 8px; margin-bottom: 10px; }
    .chips { display:flex; gap: 8px; flex-wrap: wrap; margin: 10px 0 14px; }
    .chip { padding: 8px 11px; font-size: .83rem; color: var(--muted); border: 1px solid var(--line); background: rgba(0,0,0,.18); box-shadow: none; }
    .chip.active { color: #10211d; background: var(--accent-2); border-color: transparent; }
    .device-list, .scene-list { display:grid; gap: 10px; max-height: 560px; overflow:auto; padding-right: 4px; }
    .device {
      display:grid;
      grid-template-columns: auto 1fr;
      gap: 12px;
      padding: 13px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(0,0,0,.16);
    }
    .device strong, .saved strong { display:block; overflow-wrap: anywhere; }
    .device small, .saved small { display:block; margin-top: 4px; color: var(--muted); overflow-wrap: anywhere; }
    .saved {
      padding: 13px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(0,0,0,.16);
    }
    .saved .actions { margin-top: 10px; }
    .status {
      min-height: 22px;
      margin-top: 12px;
      color: var(--muted);
      font-size: .92rem;
    }
    .status.ok { color: var(--ok); }
    .status.bad { color: var(--danger); }
    pre {
      margin: 0;
      min-height: 460px;
      max-height: 720px;
      overflow: auto;
      white-space: pre-wrap;
      color: #eafff8;
      font: .9rem/1.55 "Cascadia Mono", Consolas, monospace;
    }
    .empty {
      border: 1px dashed rgba(244,239,229,.24);
      border-radius: 18px;
      padding: 16px;
      color: var(--muted);
      background: rgba(0,0,0,.14);
    }
    @media (max-width: 1180px) {
      .layout { grid-template-columns: 1fr 1fr; }
      .right { grid-column: 1 / -1; }
    }
    @media (max-width: 760px) {
      main { width: min(100% - 18px, 720px); padding: 16px 0; }
      .hero, .layout, .split, .toolbar, .metrics { grid-template-columns: 1fr; }
      .health { min-width: 0; }
      .device-list, .scene-list { max-height: none; }
      pre { min-height: 260px; }
    }
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div>
        <h1>Syn</h1>
        <p class="lede">Build Home Assistant scenes from normal language. Choose devices, preview safe actions, save drafts, and expose saved drafts as scene entities through the Syn integration.</p>
      </div>
      <div class="health">
        <strong><span id="health-dot" class="dot"></span><span id="health-title">Checking Syn</span></strong>
        <span id="health-text">Loading diagnostics...</span>
      </div>
    </section>

    <section class="layout">
      <aside class="left">
        <div class="card">
          <div class="card-header">
            <h2>1. Describe</h2>
            <p class="hint">No YAML. Tell Syn what you want and optionally narrow by area.</p>
          </div>
          <div class="card-body">
            <label for="prompt">Scene prompt</label>
            <textarea id="prompt">Create a cozy movie night scene</textarea>
            <div class="split">
              <div>
                <label for="room">Area or search term</label>
                <input id="room" list="areas" placeholder="living room, bedroom, tv">
                <datalist id="areas"></datalist>
              </div>
              <button class="secondary" id="clear-room">All devices</button>
            </div>
            <div class="actions">
              <button id="preview">Preview</button>
              <button class="secondary" id="generate">Save draft</button>
              <button class="ghost" id="apply">Apply preview</button>
            </div>
            <div id="status" class="status">Ready.</div>
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <h2>Saved Scenes</h2>
            <p class="hint">Saved drafts appear here and in Home Assistant as scene entities after the integration refreshes.</p>
          </div>
          <div class="card-body">
            <div class="actions" style="margin-top:0">
              <button class="secondary" id="refresh-scenes">Refresh scenes</button>
              <button class="ghost" id="config">Config</button>
              <button class="ghost" id="diagnostics">Diagnostics</button>
            </div>
            <div id="scenes" class="scene-list" style="margin-top:14px">
              <div class="empty">No saved scenes loaded yet.</div>
            </div>
          </div>
        </div>
      </aside>

      <section class="card">
        <div class="card-header">
          <h2>2. Pick Devices</h2>
          <p class="hint">Syn will only touch selected devices. Search never auto-selects anything.</p>
        </div>
        <div class="card-body">
          <div class="metrics">
            <div class="metric"><b id="metric-entities">0</b><span>loaded</span></div>
            <div class="metric"><b id="metric-selected">0</b><span>selected</span></div>
            <div class="metric"><b id="metric-scenes">0</b><span>saved</span></div>
          </div>
          <div class="toolbar" style="margin-top:14px">
            <input id="search" placeholder="Search name, entity id, area, capability">
            <button class="secondary" id="select-visible">Select visible</button>
            <button class="ghost" id="select-none">Clear</button>
          </div>
          <div id="chips" class="chips"></div>
          <div class="actions" style="margin-top:0; margin-bottom:14px">
            <button class="secondary" id="refresh">Refresh devices</button>
          </div>
          <div id="entities" class="device-list">
            <div class="empty">Loading controllable devices...</div>
          </div>
        </div>
      </section>

      <aside class="right card">
        <div class="card-header">
          <h2>3. Review</h2>
          <p class="hint">Preview before applying. Save draft creates a Syn scene entity in the integration.</p>
        </div>
        <div class="card-body">
          <pre id="output">Preview output will appear here.</pre>
        </div>
      </aside>
    </section>
  </main>

  <script>
    const $ = (selector) => document.querySelector(selector);
    const base = window.location.pathname.endsWith("/") ? window.location.pathname : `${window.location.pathname}/`;
    const endpoint = (path) => `${base}${path}`;
    const state = {
      entities: [],
      selectedIds: new Set(),
      domain: "all",
      areas: [],
      scenes: [],
      lastScene: null
    };

    function setStatus(message, kind = "") {
      const status = $("#status");
      status.className = `status ${kind}`;
      status.textContent = message;
    }

    function selectedEntities() {
      return [...state.selectedIds]
        .map((id) => state.entities.find((entity) => entity.entity_id === id))
        .filter(Boolean);
    }

    function filteredEntities() {
      const search = $("#search").value.trim().toLowerCase();
      return state.entities.filter((entity) => {
        if (state.domain !== "all" && entity.domain !== state.domain) return false;
        if (!search) return true;
        const haystack = [
          entity.name,
          entity.entity_id,
          entity.room,
          entity.domain,
          ...(entity.capabilities || [])
        ].join(" ").toLowerCase();
        return haystack.includes(search);
      });
    }

    async function getJson(path) {
      const response = await fetch(endpoint(path));
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail?.message || data.detail || `HTTP ${response.status}`);
      return data;
    }

    function renderMetrics() {
      $("#metric-entities").textContent = state.entities.length;
      $("#metric-selected").textContent = selectedEntities().length;
      $("#metric-scenes").textContent = state.scenes.length;
    }

    function renderChips() {
      const domains = ["all", ...new Set(state.entities.map((entity) => entity.domain).sort())];
      $("#chips").innerHTML = domains.map((domain) =>
        `<button class="chip ${state.domain === domain ? "active" : ""}" data-domain="${domain}">${domain}</button>`
      ).join("");
      document.querySelectorAll("[data-domain]").forEach((button) => {
        button.addEventListener("click", () => {
          state.domain = button.dataset.domain;
          renderEntities();
        });
      });
    }

    function renderEntities() {
      renderChips();
      renderMetrics();
      const entities = filteredEntities();
      if (!entities.length) {
        $("#entities").innerHTML = `<div class="empty">No matching devices. Clear filters or refresh devices.</div>`;
        return;
      }
      $("#entities").innerHTML = entities.map((entity) => `
        <label class="device">
          <input type="checkbox" data-entity value="${entity.entity_id}" ${state.selectedIds.has(entity.entity_id) ? "checked" : ""}>
          <span>
            <strong>${entity.name || entity.entity_id}</strong>
            <small>${entity.entity_id}</small>
            <small>${entity.domain} | ${(entity.capabilities || []).join(", ") || "on_off"}${entity.room ? ` | ${entity.room}` : ""}</small>
          </span>
        </label>
      `).join("");
      document.querySelectorAll("[data-entity]").forEach((box) => {
        box.addEventListener("change", () => {
          if (box.checked) state.selectedIds.add(box.value);
          else state.selectedIds.delete(box.value);
          renderMetrics();
        });
      });
    }

    function renderScenes() {
      renderMetrics();
      if (!state.scenes.length) {
        $("#scenes").innerHTML = `<div class="empty">No saved scenes yet. Use Save draft, then refresh here or wait for Home Assistant to refresh the Syn integration.</div>`;
        return;
      }
      $("#scenes").innerHTML = state.scenes.map((scene) => `
        <article class="saved">
          <strong>${scene.name || scene.id}</strong>
          <small>${scene.id}</small>
          <small>${scene.target_room || "No room"} | ${scene.status || "draft"}</small>
          <div class="actions">
            <button class="secondary" data-load-scene="${scene.id}">View</button>
            <button class="ghost" data-run-scene="${scene.id}">Run</button>
          </div>
        </article>
      `).join("");
      document.querySelectorAll("[data-load-scene]").forEach((button) => {
        button.addEventListener("click", () => loadScene(button.dataset.loadScene));
      });
      document.querySelectorAll("[data-run-scene]").forEach((button) => {
        button.addEventListener("click", () => runSavedScene(button.dataset.runScene));
      });
    }

    async function loadAreas() {
      try {
        const data = await getJson("areas");
        state.areas = data.areas || [];
        $("#areas").innerHTML = state.areas.map((area) => `<option value="${area.area_id}">${area.name}</option>`).join("");
      } catch {
        state.areas = [];
      }
    }

    async function loadEntities() {
      const room = $("#room").value.trim();
      const query = room ? `?room_id=${encodeURIComponent(room)}` : "";
      setStatus("Refreshing devices...");
      try {
        const data = await getJson(`entities${query}`);
        state.entities = data.entities || [];
        const available = new Set(state.entities.map((entity) => entity.entity_id));
        state.selectedIds = new Set([...state.selectedIds].filter((id) => available.has(id)));
        renderEntities();
        setStatus(`Loaded ${state.entities.length} devices.`, state.entities.length ? "ok" : "bad");
      } catch (error) {
        state.entities = [];
        renderEntities();
        setStatus(`Device discovery failed: ${error.message}`, "bad");
      }
    }

    async function loadScenes() {
      try {
        const data = await getJson("scenes");
        state.scenes = data.scenes || [];
        renderScenes();
      } catch (error) {
        $("#scenes").innerHTML = `<div class="empty">Could not load saved scenes: ${error.message}</div>`;
      }
    }

    async function loadScene(sceneId) {
      const data = await getJson(`get_scene/${sceneId}`);
      $("#output").textContent = JSON.stringify(data, null, 2);
      state.lastScene = data.scene || data;
      setStatus("Saved scene loaded.", "ok");
    }

    async function runSavedScene(sceneId) {
      await loadScene(sceneId);
      await applyScene(state.lastScene);
    }

    function buildPayload() {
      return {
        user_prompt: $("#prompt").value.trim(),
        room_id: $("#room").value.trim() || null,
        entities: selectedEntities()
      };
    }

    async function send(path, label) {
      const payload = buildPayload();
      if (!payload.entities.length) {
        setStatus("Select at least one device first.", "bad");
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
        $("#output").textContent = JSON.stringify(data, null, 2);
        if (!response.ok) throw new Error(data.detail?.message || data.detail || `HTTP ${response.status}`);
        state.lastScene = data.scene || null;
        setStatus(path === "generate_scene" ? "Draft saved. It will appear as a Syn scene entity." : "Preview ready.", "ok");
        if (path === "generate_scene") await loadScenes();
      } catch (error) {
        setStatus(error.message, "bad");
      } finally {
        document.querySelectorAll("button").forEach((button) => button.disabled = false);
      }
    }

    async function applyScene(scene) {
      if (!scene) {
        setStatus("Preview or load a scene first.", "bad");
        return;
      }
      setStatus("Applying scene...");
      const response = await fetch(endpoint("execute_scene"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({scene})
      });
      const data = await response.json();
      $("#output").textContent = JSON.stringify(data, null, 2);
      if (!response.ok || data.overall_status === "failed") {
        throw new Error(data.message || "Scene execution failed.");
      }
      setStatus(`Applied ${data.actions_executed || 0} actions.`, "ok");
    }

    async function diagnostics() {
      const data = await getJson("discovery_status");
      $("#output").textContent = JSON.stringify(data, null, 2);
      $("#health-dot").classList.toggle("ok", Boolean(data.ok));
      $("#health-title").textContent = data.ok ? "Syn ready" : "Syn needs attention";
      $("#health-text").textContent = data.message || "Diagnostics loaded.";
    }

    async function config() {
      const data = await getJson("config_status");
      $("#output").textContent = JSON.stringify(data, null, 2);
      setStatus(data.api_key_configured ? "AI configuration is loaded." : "AI key is missing.", data.api_key_configured ? "ok" : "bad");
    }

    $("#preview").addEventListener("click", () => send("preview_scene", "Previewing"));
    $("#generate").addEventListener("click", () => send("generate_scene", "Saving draft"));
    $("#apply").addEventListener("click", () => applyScene(state.lastScene).catch((error) => setStatus(error.message, "bad")));
    $("#refresh").addEventListener("click", loadEntities);
    $("#refresh-scenes").addEventListener("click", loadScenes);
    $("#config").addEventListener("click", config);
    $("#diagnostics").addEventListener("click", diagnostics);
    $("#clear-room").addEventListener("click", () => { $("#room").value = ""; loadEntities(); });
    $("#room").addEventListener("change", loadEntities);
    $("#search").addEventListener("input", renderEntities);
    $("#select-visible").addEventListener("click", () => {
      filteredEntities().forEach((entity) => state.selectedIds.add(entity.entity_id));
      renderEntities();
    });
    $("#select-none").addEventListener("click", () => {
      state.selectedIds.clear();
      renderEntities();
    });

    loadAreas();
    loadEntities();
    loadScenes();
    diagnostics().catch(() => {
      $("#health-title").textContent = "Diagnostics unavailable";
      $("#health-text").textContent = "Open Config for details.";
    });
  </script>
</body>
</html>
"""

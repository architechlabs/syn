"""Small ingress-safe web UI for the Syn add-on."""

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Syn</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #101820;
      --panel: rgba(255, 255, 255, 0.08);
      --panel-strong: rgba(255, 255, 255, 0.14);
      --text: #f5efe6;
      --muted: #b9c4c9;
      --accent: #f0b35a;
      --accent-2: #76d6c4;
      --danger: #ff7f7f;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--text);
      background:
        radial-gradient(circle at 12% 8%, rgba(240, 179, 90, 0.22), transparent 28rem),
        radial-gradient(circle at 88% 16%, rgba(118, 214, 196, 0.18), transparent 24rem),
        linear-gradient(135deg, #101820 0%, #1d2a2f 52%, #111819 100%);
    }
    main {
      width: min(1120px, calc(100% - 32px));
      margin: 0 auto;
      padding: 40px 0;
    }
    .hero {
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: 24px;
      align-items: stretch;
    }
    .card {
      border: 1px solid rgba(255, 255, 255, 0.16);
      border-radius: 28px;
      background: var(--panel);
      box-shadow: 0 24px 80px rgba(0, 0, 0, 0.28);
      padding: 28px;
      backdrop-filter: blur(20px);
    }
    h1 {
      margin: 0 0 10px;
      font-size: clamp(2.6rem, 7vw, 5.6rem);
      line-height: 0.9;
      letter-spacing: -0.08em;
    }
    p {
      margin: 0;
      color: var(--muted);
      font-size: 1.05rem;
      line-height: 1.6;
    }
    label {
      display: block;
      margin: 18px 0 8px;
      color: var(--muted);
      font-size: 0.78rem;
      font-family: Verdana, sans-serif;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }
    input, textarea {
      width: 100%;
      border: 1px solid rgba(255, 255, 255, 0.18);
      border-radius: 18px;
      color: var(--text);
      background: rgba(0, 0, 0, 0.22);
      font: 1rem/1.45 Consolas, "Courier New", monospace;
      padding: 14px 16px;
      outline: none;
    }
    textarea { min-height: 170px; resize: vertical; }
    input:focus, textarea:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(240, 179, 90, 0.18);
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 18px;
    }
    button, a.button {
      border: 0;
      border-radius: 999px;
      color: #172022;
      background: var(--accent);
      cursor: pointer;
      font: 700 0.92rem Verdana, sans-serif;
      padding: 12px 18px;
      text-decoration: none;
    }
    button.secondary, a.button.secondary {
      color: var(--text);
      background: var(--panel-strong);
    }
    button:disabled { cursor: wait; opacity: 0.72; }
    .status {
      min-height: 1.5rem;
      margin-top: 16px;
      color: var(--accent-2);
      font-family: Consolas, "Courier New", monospace;
    }
    .status.error { color: var(--danger); }
    pre {
      min-height: 360px;
      max-height: 68vh;
      margin: 0;
      overflow: auto;
      white-space: pre-wrap;
      color: #eaf7f4;
      font: 0.9rem/1.55 Consolas, "Courier New", monospace;
    }
    .hint {
      margin-top: 18px;
      padding: 16px;
      border-radius: 20px;
      background: rgba(0, 0, 0, 0.16);
    }
    code { color: var(--accent); }
    @media (max-width: 840px) {
      main { width: min(100% - 20px, 1120px); padding: 20px 0; }
      .hero { grid-template-columns: 1fr; }
      .card { padding: 22px; border-radius: 22px; }
    }
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div class="card">
        <h1>Syn</h1>
        <p>Draft Home Assistant scenes from a prompt and the entities you provide. This page is served from the add-on root, so Home Assistant ingress opens a real UI instead of FastAPI's 404 response.</p>

        <label for="prompt">Scene prompt</label>
        <input id="prompt" value="Create a cozy movie night scene">

        <label for="room">Room ID</label>
        <input id="room" value="living_room">

        <label for="entities">Entities JSON</label>
        <textarea id="entities">[
  {
    "entity_id": "light.living_room",
    "domain": "light",
    "capabilities": ["on_off", "brightness", "color_temp"],
    "state": {"value": "off"},
    "room": "living_room"
  }
]</textarea>

        <div class="actions">
          <button id="preview">Preview scene</button>
          <button id="generate">Generate and save</button>
          <a class="button secondary" id="docs" href="docs">API docs</a>
        </div>
        <div id="status" class="status">Ready.</div>
        <div class="hint">
          <p>Tip: paste entity data from the Syn integration or Developer Tools. API calls use relative URLs like <code>preview_scene</code>, which keeps them working under ingress paths such as <code>/app/..._syn/</code>.</p>
        </div>
      </div>

      <div class="card">
        <pre id="output">Scene output will appear here.</pre>
      </div>
    </section>
  </main>

  <script>
    const statusEl = document.querySelector("#status");
    const outputEl = document.querySelector("#output");
    const buttons = [...document.querySelectorAll("button")];
    const ingressBase = window.location.pathname.endsWith("/")
      ? window.location.pathname
      : `${window.location.pathname}/`;

    document.querySelector("#docs").href = `${ingressBase}docs`;

    function endpoint(path) {
      return `${ingressBase}${path}`;
    }

    function payload() {
      return {
        user_prompt: document.querySelector("#prompt").value,
        room_id: document.querySelector("#room").value || null,
        entities: JSON.parse(document.querySelector("#entities").value || "[]")
      };
    }

    async function send(path, label) {
      statusEl.classList.remove("error");
      statusEl.textContent = `${label}...`;
      buttons.forEach((button) => button.disabled = true);
      try {
        const response = await fetch(endpoint(path), {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload())
        });
        const data = await response.json();
        outputEl.textContent = JSON.stringify(data, null, 2);
        if (!response.ok) {
          throw new Error(data.detail || data.errors || `HTTP ${response.status}`);
        }
        statusEl.textContent = "Scene response received.";
      } catch (error) {
        statusEl.classList.add("error");
        statusEl.textContent = `Error: ${error.message}`;
      } finally {
        buttons.forEach((button) => button.disabled = false);
      }
    }

    document.querySelector("#preview").addEventListener("click", () => send("preview_scene", "Previewing"));
    document.querySelector("#generate").addEventListener("click", () => send("generate_scene", "Generating"));
  </script>
</body>
</html>
"""

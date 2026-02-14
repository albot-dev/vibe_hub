from __future__ import annotations

API_UI_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agent Hub API Console</title>
  <style>
    :root {
      --bg: #f5f7fb;
      --panel: #ffffff;
      --text: #162334;
      --muted: #5d6f84;
      --border: #d6dce5;
      --accent: #1653b5;
      --accent-soft: #dbe8ff;
      --ok: #0f7a42;
      --warn: #9a5b00;
      --err: #b82727;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      padding: 1.25rem;
      background: radial-gradient(1000px 600px at 5% -20%, #dbe8ff 0%, var(--bg) 60%);
      color: var(--text);
      font-family: "IBM Plex Sans", "Segoe UI", Arial, sans-serif;
      line-height: 1.45;
    }

    .wrap {
      max-width: 1200px;
      margin: 0 auto;
      display: grid;
      gap: 1rem;
    }

    .hero {
      background: linear-gradient(120deg, #ecf3ff, #ffffff);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1rem 1.1rem;
    }

    .hero h1 {
      margin: 0;
      font-size: 1.35rem;
    }

    .hero p {
      margin: 0.5rem 0 0;
      color: var(--muted);
    }

    .links {
      margin-top: 0.65rem;
      display: flex;
      gap: 0.75rem;
      flex-wrap: wrap;
      font-size: 0.95rem;
    }

    .links a {
      color: var(--accent);
      text-decoration: none;
      border-bottom: 1px solid transparent;
    }

    .links a:hover {
      border-bottom-color: var(--accent);
    }

    .grid {
      display: grid;
      grid-template-columns: minmax(320px, 1fr) minmax(320px, 1fr);
      gap: 1rem;
      align-items: start;
    }

    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 0.95rem;
      box-shadow: 0 1px 4px rgba(19, 43, 74, 0.06);
    }

    .panel h2 {
      margin: 0 0 0.7rem;
      font-size: 1.02rem;
    }

    .field {
      display: grid;
      gap: 0.35rem;
      margin-bottom: 0.65rem;
    }

    .field label {
      font-weight: 600;
      font-size: 0.9rem;
    }

    .row {
      display: grid;
      grid-template-columns: 140px 1fr;
      gap: 0.55rem;
    }

    .triple {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0.55rem;
    }

    input,
    select,
    textarea,
    button {
      font: inherit;
    }

    input,
    select,
    textarea {
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.55rem 0.6rem;
      background: #fff;
      color: var(--text);
    }

    textarea {
      min-height: 124px;
      resize: vertical;
      font-family: "IBM Plex Mono", "Menlo", "Consolas", monospace;
      font-size: 0.88rem;
    }

    .actions {
      display: flex;
      gap: 0.55rem;
      flex-wrap: wrap;
      margin-top: 0.55rem;
    }

    button {
      border: 1px solid transparent;
      border-radius: 8px;
      padding: 0.55rem 0.8rem;
      background: #ebf0f7;
      color: #1c2f4a;
      cursor: pointer;
    }

    button.primary {
      background: var(--accent);
      color: #fff;
    }

    button:disabled {
      opacity: 0.65;
      cursor: not-allowed;
    }

    .preset-wrap {
      display: flex;
      flex-wrap: wrap;
      gap: 0.45rem;
      margin-top: 0.25rem;
    }

    .preset-btn {
      border: 1px solid #b9cae3;
      background: var(--accent-soft);
      color: #19407a;
      font-size: 0.82rem;
      padding: 0.4rem 0.55rem;
    }

    .status {
      font-weight: 700;
      padding: 0.45rem 0.55rem;
      border-radius: 8px;
      margin-bottom: 0.7rem;
      background: #eef3f9;
    }

    .status.ok {
      color: var(--ok);
      background: #e8f8ee;
    }

    .status.warn {
      color: var(--warn);
      background: #fff4e5;
    }

    .status.err {
      color: var(--err);
      background: #fdeced;
    }

    details {
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #fcfdff;
      margin-bottom: 0.55rem;
    }

    summary {
      cursor: pointer;
      padding: 0.45rem 0.55rem;
      font-weight: 600;
      color: #243b5b;
    }

    pre {
      margin: 0;
      padding: 0.55rem;
      border-top: 1px solid var(--border);
      background: #f8fafc;
      overflow: auto;
      font-family: "IBM Plex Mono", "Menlo", "Consolas", monospace;
      font-size: 0.84rem;
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 360px;
    }

    .hint {
      color: var(--muted);
      font-size: 0.83rem;
      margin-top: -0.3rem;
      margin-bottom: 0.55rem;
    }

    @media (max-width: 920px) {
      .grid {
        grid-template-columns: 1fr;
      }

      .triple {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <header class="hero">
      <h1>Agent Hub API Console</h1>
      <p>Call API endpoints directly with method, path, auth headers, and JSON payloads.</p>
      <div class="links">
        <a href="/docs" target="_blank" rel="noopener">OpenAPI docs</a>
        <a href="/openapi.json" target="_blank" rel="noopener">OpenAPI JSON</a>
        <a href="/health" target="_blank" rel="noopener">Health</a>
      </div>
    </header>

    <main class="grid">
      <section class="panel">
        <h2>Request</h2>

        <div class="field">
          <label for="baseUrl">Base URL</label>
          <input id="baseUrl" type="text" autocomplete="off">
        </div>

        <div class="row">
          <div class="field">
            <label for="method">Method</label>
            <select id="method">
              <option>GET</option>
              <option>POST</option>
              <option>PATCH</option>
              <option>PUT</option>
              <option>DELETE</option>
            </select>
          </div>
          <div class="field">
            <label for="path">Path</label>
            <input id="path" type="text" placeholder="/projects" autocomplete="off">
          </div>
        </div>

        <div class="field">
          <label for="query">Query String (optional)</label>
          <input id="query" type="text" placeholder="page=1&page_size=20" autocomplete="off">
        </div>

        <div class="triple">
          <div class="field">
            <label for="apiKey">X-API-Key (optional)</label>
            <input id="apiKey" type="password" autocomplete="off">
          </div>
          <div class="field">
            <label for="bearerToken">Bearer Token (optional)</label>
            <input id="bearerToken" type="password" autocomplete="off" placeholder="without 'Bearer ' prefix">
          </div>
        </div>

        <div class="field">
          <label for="extraHeaders">Extra Headers (JSON object)</label>
          <textarea id="extraHeaders">{}</textarea>
          <div class="hint">Example: {"X-Trace-ID":"demo-trace-id"}</div>
        </div>

        <div class="field">
          <label for="requestBody">JSON Body</label>
          <textarea id="requestBody">{}</textarea>
          <div class="hint">Body is sent for POST/PATCH/PUT/DELETE when non-empty.</div>
        </div>

        <div class="field">
          <label>Presets</label>
          <div class="preset-wrap" id="presets"></div>
        </div>

        <div class="actions">
          <button id="autofillBtn" type="button">Autofill From .env</button>
          <button id="sendBtn" class="primary">Send Request</button>
          <button id="clearBtn" type="button">Clear Response</button>
        </div>
      </section>

      <section class="panel">
        <h2>Response</h2>
        <div id="statusLine" class="status">Ready</div>

        <details open>
          <summary>cURL Preview</summary>
          <pre id="curlPreview">curl --request GET --url http://127.0.0.1:8000/health</pre>
        </details>

        <details open>
          <summary>Response Headers</summary>
          <pre id="responseHeaders">(none)</pre>
        </details>

        <details open>
          <summary>Response Body</summary>
          <pre id="responseBody">(none)</pre>
        </details>
      </section>
    </main>
  </div>

  <script>
    (function () {
      const fallbackPresets = [
        { label: "GET /health", method: "GET", path: "/health", query: "", body: "" },
        { label: "GET /projects", method: "GET", path: "/projects", query: "", body: "" },
        {
          label: "POST /projects",
          method: "POST",
          path: "/projects",
          query: "",
          body: JSON.stringify(
            {
              name: "demo-project",
              repo_url: "https://github.com/example/repo",
              default_branch: "main"
            },
            null,
            2
          )
        },
        { label: "GET /projects/{project_id}/dashboard", method: "GET", path: "/projects/1/dashboard", query: "", body: "" },
        {
          label: "POST /projects/{project_id}/autopilot/run",
          method: "POST",
          path: "/projects/1/autopilot/run",
          query: "",
          body: JSON.stringify({ max_items: 2 }, null, 2)
        },
        {
          label: "POST /auth/token",
          method: "POST",
          path: "/auth/token",
          query: "",
          body: JSON.stringify({ subject: "ui-user", role: "maintainer" }, null, 2)
        }
      ];
      const presetMethodOrder = ["GET", "POST", "PATCH", "PUT", "DELETE"];

      const methodEl = document.getElementById("method");
      const baseUrlEl = document.getElementById("baseUrl");
      const pathEl = document.getElementById("path");
      const queryEl = document.getElementById("query");
      const apiKeyEl = document.getElementById("apiKey");
      const bearerTokenEl = document.getElementById("bearerToken");
      const extraHeadersEl = document.getElementById("extraHeaders");
      const bodyEl = document.getElementById("requestBody");
      const autofillBtn = document.getElementById("autofillBtn");
      const sendBtn = document.getElementById("sendBtn");
      const clearBtn = document.getElementById("clearBtn");
      const curlPreviewEl = document.getElementById("curlPreview");
      const statusLineEl = document.getElementById("statusLine");
      const responseHeadersEl = document.getElementById("responseHeaders");
      const responseBodyEl = document.getElementById("responseBody");
      const presetsEl = document.getElementById("presets");
      let prefillPayload = null;

      const defaultBaseUrl = window.location.origin || "http://127.0.0.1:8000";
      baseUrlEl.value = defaultBaseUrl;
      pathEl.value = "/health";
      methodEl.value = "GET";
      bodyEl.value = "";

      function setStatus(message, variant) {
        statusLineEl.textContent = message;
        statusLineEl.className = "status";
        if (variant) {
          statusLineEl.classList.add(variant);
        }
      }

      function shellEscape(value) {
        return "'" + String(value).replace(/'/g, `'"'"'`) + "'";
      }

      function parseExtraHeaders() {
        const raw = extraHeadersEl.value.trim();
        if (!raw) {
          return {};
        }
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          throw new Error("Extra headers must be a JSON object.");
        }
        return parsed;
      }

      function buildHeaders() {
        const headers = {};
        const apiKey = apiKeyEl.value.trim();
        const bearerToken = bearerTokenEl.value.trim();

        if (apiKey) {
          headers["X-API-Key"] = apiKey;
        }
        if (bearerToken) {
          headers["Authorization"] = "Bearer " + bearerToken;
        }

        const extra = parseExtraHeaders();
        Object.entries(extra).forEach(function (entry) {
          const key = entry[0];
          const value = entry[1];
          if (value !== undefined && value !== null) {
            headers[String(key)] = String(value);
          }
        });
        return headers;
      }

      function buildRequestUrl() {
        const base = baseUrlEl.value.trim() || defaultBaseUrl;
        const rawPath = pathEl.value.trim() || "/";
        const path = rawPath.startsWith("http://") || rawPath.startsWith("https://")
          ? rawPath
          : new URL(rawPath, base).toString();
        const url = new URL(path);

        const query = queryEl.value.trim();
        if (query) {
          const cleaned = query.startsWith("?") ? query.slice(1) : query;
          const params = new URLSearchParams(cleaned);
          params.forEach(function (value, key) {
            url.searchParams.set(key, value);
          });
        }
        return url.toString();
      }

      function shouldSendBody(method) {
        return method !== "GET" && method !== "HEAD";
      }

      function parseBodyIfNeeded(method) {
        const raw = bodyEl.value.trim();
        if (!shouldSendBody(method) || !raw) {
          return null;
        }
        const parsed = JSON.parse(raw);
        return JSON.stringify(parsed);
      }

      function sortedObjectEntries(value) {
        return Object.keys(value || {})
          .sort()
          .map(function (key) {
            return [key, value[key]];
          });
      }

      function resolveSchemaRef(schema, openApi) {
        if (!schema || typeof schema !== "object") {
          return null;
        }
        let current = schema;
        const seenRefs = {};

        while (current && current.$ref) {
          const ref = current.$ref;
          if (seenRefs[ref]) {
            break;
          }
          seenRefs[ref] = true;
          if (!ref.startsWith("#/components/schemas/")) {
            break;
          }
          const name = ref.slice("#/components/schemas/".length);
          const resolved = openApi.components && openApi.components.schemas && openApi.components.schemas[name];
          if (!resolved) {
            break;
          }
          current = resolved;
        }

        return current || schema;
      }

      function chooseSchemaVariant(schema, openApi) {
        const resolved = resolveSchemaRef(schema, openApi);
        if (!resolved || typeof resolved !== "object") {
          return null;
        }

        const variants = resolved.anyOf || resolved.oneOf;
        if (Array.isArray(variants) && variants.length) {
          for (let i = 0; i < variants.length; i += 1) {
            const candidate = resolveSchemaRef(variants[i], openApi);
            if (candidate && candidate.type !== "null") {
              return candidate;
            }
          }
          return resolveSchemaRef(variants[0], openApi);
        }

        return resolved;
      }

      function sampleString(fieldName, schema) {
        const name = String(fieldName || "").toLowerCase();
        if (name.includes("repo_url") || name.endsWith("url")) {
          return "https://github.com/example/repo";
        }
        if (name.includes("branch")) {
          return "main";
        }
        if (name.includes("objective")) {
          return "Implement feature with tests and docs.";
        }
        if (name === "subject") {
          return "ui-user";
        }
        if (name === "role") {
          return "maintainer";
        }
        if (name.includes("created_by") || name.includes("requested_by")) {
          return "ui-console";
        }

        if (schema && schema.format === "date-time") {
          return "2026-01-01T00:00:00Z";
        }
        if (schema && schema.format === "date") {
          return "2026-01-01";
        }
        if (schema && (schema.format === "uri" || schema.format === "url")) {
          return "https://example.com";
        }
        if (schema && typeof schema.minLength === "number" && schema.minLength >= 10) {
          return "sample-value-123";
        }
        return "string";
      }

      function buildExampleFromSchema(schema, openApi, depth, fieldName) {
        if (depth > 5) {
          return undefined;
        }
        const resolved = chooseSchemaVariant(schema, openApi);
        if (!resolved) {
          return undefined;
        }

        if (resolved.example !== undefined) {
          return resolved.example;
        }
        if (resolved.default !== undefined) {
          return resolved.default;
        }
        if (resolved.const !== undefined) {
          return resolved.const;
        }
        if (Array.isArray(resolved.enum) && resolved.enum.length) {
          return resolved.enum[0];
        }

        if (Array.isArray(resolved.allOf) && resolved.allOf.length) {
          const merged = {};
          let hasObjectPiece = false;
          resolved.allOf.forEach(function (part) {
            const piece = buildExampleFromSchema(part, openApi, depth + 1, fieldName);
            if (piece && typeof piece === "object" && !Array.isArray(piece)) {
              Object.assign(merged, piece);
              hasObjectPiece = true;
            }
          });
          if (hasObjectPiece) {
            return merged;
          }
        }

        if (resolved.type === "object" || resolved.properties) {
          const properties = resolved.properties || {};
          const required = Array.isArray(resolved.required) ? resolved.required : [];
          const propertyEntries = sortedObjectEntries(properties);
          const result = {};

          propertyEntries.forEach(function (entry) {
            const name = entry[0];
            const propertySchema = entry[1];
            const propertyVariant = chooseSchemaVariant(propertySchema, openApi);
            const include = required.indexOf(name) >= 0 || (propertyVariant && propertyVariant.default !== undefined);
            if (!include) {
              return;
            }
            const value = buildExampleFromSchema(propertySchema, openApi, depth + 1, name);
            if (value !== undefined) {
              result[name] = value;
            }
          });

          if (!Object.keys(result).length && propertyEntries.length) {
            const first = propertyEntries[0];
            const fallbackValue = buildExampleFromSchema(first[1], openApi, depth + 1, first[0]);
            if (fallbackValue !== undefined) {
              result[first[0]] = fallbackValue;
            }
          }
          return result;
        }

        if (resolved.type === "array") {
          const itemValue = buildExampleFromSchema(resolved.items || {}, openApi, depth + 1, fieldName);
          return itemValue === undefined ? [] : [itemValue];
        }

        if (resolved.type === "integer") {
          if (typeof resolved.minimum === "number") {
            return Math.trunc(resolved.minimum);
          }
          return 1;
        }

        if (resolved.type === "number") {
          if (typeof resolved.minimum === "number") {
            return resolved.minimum;
          }
          return 1;
        }

        if (resolved.type === "boolean") {
          return false;
        }

        if (resolved.type === "string") {
          return sampleString(fieldName, resolved);
        }

        if (resolved.type === "null") {
          return null;
        }

        return undefined;
      }

      function findJsonSchema(requestBody) {
        if (!requestBody || !requestBody.content) {
          return null;
        }
        if (requestBody.content["application/json"] && requestBody.content["application/json"].schema) {
          return requestBody.content["application/json"].schema;
        }
        const mediaType = Object.keys(requestBody.content).find(function (entry) {
          return entry.toLowerCase().includes("json");
        });
        if (!mediaType || !requestBody.content[mediaType]) {
          return null;
        }
        return requestBody.content[mediaType].schema || null;
      }

      function buildBodyPreset(operation, openApi) {
        const schema = findJsonSchema(operation.requestBody);
        if (!schema) {
          return "";
        }
        const example = buildExampleFromSchema(schema, openApi, 0, "");
        if (example === undefined || example === null) {
          return operation.requestBody && operation.requestBody.required ? "{}" : "";
        }
        return JSON.stringify(example, null, 2);
      }

      function sampleParameterValue(parameter, openApi) {
        if (parameter.example !== undefined) {
          return parameter.example;
        }
        const schema = chooseSchemaVariant(parameter.schema || {}, openApi);
        if (schema && schema.example !== undefined) {
          return schema.example;
        }
        if (schema && schema.default !== undefined) {
          return schema.default;
        }
        if (schema && Array.isArray(schema.enum) && schema.enum.length) {
          return schema.enum[0];
        }

        const name = String(parameter.name || "").toLowerCase();
        if (schema && schema.type === "integer") {
          return 1;
        }
        if (schema && schema.type === "number") {
          return 1;
        }
        if (schema && schema.type === "boolean") {
          return false;
        }
        if (name === "id" || name.endsWith("_id") || name.includes("id")) {
          return 1;
        }
        return sampleString(name, schema || null);
      }

      function applyPathParameters(pathTemplate, operation, openApi) {
        let resolvedPath = pathTemplate;
        const parameters = Array.isArray(operation.parameters) ? operation.parameters : [];
        parameters
          .filter(function (parameter) {
            return parameter.in === "path";
          })
          .forEach(function (parameter) {
            const token = "{" + parameter.name + "}";
            const value = sampleParameterValue(parameter, openApi);
            resolvedPath = resolvedPath.split(token).join(encodeURIComponent(String(value)));
          });
        return resolvedPath;
      }

      function buildRequiredQuery(operation, openApi) {
        const parameters = Array.isArray(operation.parameters) ? operation.parameters : [];
        const pairs = [];
        parameters
          .filter(function (parameter) {
            return parameter.in === "query" && parameter.required;
          })
          .forEach(function (parameter) {
            const value = sampleParameterValue(parameter, openApi);
            pairs.push(encodeURIComponent(parameter.name) + "=" + encodeURIComponent(String(value)));
          });
        return pairs.join("&");
      }

      function buildPresetsFromOpenApi(openApi) {
        if (!openApi || typeof openApi !== "object" || !openApi.paths) {
          return [];
        }
        const built = [];
        const pathEntries = sortedObjectEntries(openApi.paths);

        pathEntries.forEach(function (pathEntry) {
          const pathTemplate = pathEntry[0];
          const pathItem = pathEntry[1] || {};
          const methods = sortedObjectEntries(pathItem)
            .filter(function (methodEntry) {
              return presetMethodOrder.indexOf(methodEntry[0].toUpperCase()) >= 0;
            })
            .sort(function (a, b) {
              return presetMethodOrder.indexOf(a[0].toUpperCase()) - presetMethodOrder.indexOf(b[0].toUpperCase());
            });

          methods.forEach(function (methodEntry) {
            const method = methodEntry[0].toUpperCase();
            const operation = methodEntry[1] || {};
            built.push({
              label: method + " " + pathTemplate,
              method: method,
              path: applyPathParameters(pathTemplate, operation, openApi),
              query: buildRequiredQuery(operation, openApi),
              body: buildBodyPreset(operation, openApi),
              summary: operation.summary || ""
            });
          });
        });

        // This endpoint is intentionally not listed in OpenAPI but is useful in the console.
        built.push({
          label: "GET /ui/prefill",
          method: "GET",
          path: "/ui/prefill",
          query: "",
          body: "",
          summary: "Load safe values from server env for UI autofill"
        });

        return built;
      }

      function normalizePreset(preset) {
        return {
          label: String(preset.label || (String(preset.method || "GET").toUpperCase() + " " + String(preset.path || "/"))),
          method: String(preset.method || "GET").toUpperCase(),
          path: String(preset.path || "/"),
          query: String(preset.query || ""),
          body: String(preset.body || ""),
          summary: String(preset.summary || "")
        };
      }

      function renderPresets(presetList) {
        presetsEl.innerHTML = "";
        presetList.map(normalizePreset).forEach(function (preset) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "preset-btn";
          button.textContent = preset.label;
          if (preset.summary) {
            button.title = preset.summary;
          }
          button.addEventListener("click", function () {
            methodEl.value = preset.method;
            pathEl.value = preset.path;
            queryEl.value = preset.query;
            bodyEl.value = preset.body;
            buildCurlPreview();
          });
          presetsEl.appendChild(button);
        });
      }

      async function loadOpenApiPresets() {
        try {
          const response = await fetch("/openapi.json", { method: "GET" });
          if (!response.ok) {
            throw new Error("HTTP " + response.status);
          }
          const openApi = await response.json();
          const presets = buildPresetsFromOpenApi(openApi);
          if (presets.length) {
            renderPresets(presets);
          }
        } catch (error) {
          console.warn("Failed to load OpenAPI presets:", error);
        }
      }

      function buildCurlPreview() {
        try {
          const method = methodEl.value.toUpperCase();
          const url = buildRequestUrl();
          const headers = buildHeaders();
          const body = parseBodyIfNeeded(method);
          const lines = [
            "curl --request " + method,
            "  --url " + shellEscape(url)
          ];

          Object.keys(headers).forEach(function (name) {
            lines.push("  --header " + shellEscape(name + ": " + headers[name]));
          });

          if (body !== null) {
            if (!headers["Content-Type"]) {
              lines.push("  --header " + shellEscape("Content-Type: application/json"));
            }
            lines.push("  --data " + shellEscape(body));
          }
          curlPreviewEl.textContent = lines.join("\\n");
        } catch (error) {
          curlPreviewEl.textContent = "Preview error: " + error.message;
        }
      }

      function clearResponse() {
        setStatus("Ready");
        responseHeadersEl.textContent = "(none)";
        responseBodyEl.textContent = "(none)";
      }

      async function readResponseDetail(response) {
        const raw = await response.text();
        if (!raw) {
          return "HTTP " + response.status;
        }

        try {
          const parsed = JSON.parse(raw);
          if (parsed && typeof parsed.detail === "string") {
            return parsed.detail;
          }
          return JSON.stringify(parsed);
        } catch (_) {
          return raw;
        }
      }

      function prepareTokenRequestTemplate() {
        methodEl.value = "POST";
        pathEl.value = "/auth/token";
        queryEl.value = "";
        bodyEl.value = JSON.stringify(
          {
            subject: "ui-user",
            role: "maintainer"
          },
          null,
          2
        );
      }

      async function autofillFromEnv() {
        autofillBtn.disabled = true;
        setStatus("Loading values from server env...", "warn");

        try {
          const response = await fetch("/ui/prefill", { method: "GET" });
          if (!response.ok) {
            throw new Error(await readResponseDetail(response));
          }

          const payload = await response.json();
          prefillPayload = payload;

          if (payload.base_url) {
            baseUrlEl.value = String(payload.base_url);
          }
          if (payload.api_key) {
            apiKeyEl.value = String(payload.api_key);
          }

          if (!bearerTokenEl.value.trim() && payload.auth_require_roles) {
            prepareTokenRequestTemplate();
            setStatus("Autofill complete. API key loaded. Click Send Request to issue a JWT token.", "ok");
          } else {
            setStatus("Autofill complete. API key loaded from server env.", "ok");
          }
          buildCurlPreview();
        } catch (error) {
          setStatus("Autofill failed: " + error.message, "err");
        } finally {
          autofillBtn.disabled = false;
        }
      }

      async function sendRequest() {
        sendBtn.disabled = true;
        setStatus("Sending request...", "warn");

        const start = performance.now();
        try {
          const method = methodEl.value.toUpperCase();
          const url = buildRequestUrl();
          const headers = buildHeaders();
          const body = parseBodyIfNeeded(method);

          if (body !== null && !headers["Content-Type"]) {
            headers["Content-Type"] = "application/json";
          }

          const response = await fetch(url, {
            method: method,
            headers: headers,
            body: body
          });

          const elapsedMs = Math.round(performance.now() - start);
          let statusText = response.status + " " + response.statusText + " (" + elapsedMs + " ms)";
          const variant = response.ok ? "ok" : (response.status >= 400 && response.status < 500 ? "warn" : "err");
          setStatus(statusText, variant);

          const headerLines = [];
          response.headers.forEach(function (value, key) {
            headerLines.push(key + ": " + value);
          });
          responseHeadersEl.textContent = headerLines.length ? headerLines.join("\\n") : "(none)";

          const rawText = await response.text();
          const contentType = response.headers.get("content-type") || "";
          let parsedJson = null;
          if (rawText && contentType.includes("application/json")) {
            try {
              parsedJson = JSON.parse(rawText);
              responseBodyEl.textContent = JSON.stringify(parsedJson, null, 2);
            } catch (_) {
              responseBodyEl.textContent = rawText;
            }
          } else {
            responseBodyEl.textContent = rawText || "(empty body)";
          }

          if (response.ok && parsedJson && typeof parsedJson.access_token === "string" && parsedJson.access_token) {
            bearerTokenEl.value = parsedJson.access_token;
            statusText = statusText + " - bearer token auto-filled";
            setStatus(statusText, "ok");
          }
        } catch (error) {
          setStatus("Request failed: " + error.message, "err");
          responseHeadersEl.textContent = "(none)";
          responseBodyEl.textContent = String(error);
        } finally {
          sendBtn.disabled = false;
          buildCurlPreview();
        }
      }

      renderPresets(fallbackPresets);

      [methodEl, baseUrlEl, pathEl, queryEl, apiKeyEl, bearerTokenEl, extraHeadersEl, bodyEl]
        .forEach(function (element) {
          element.addEventListener("input", buildCurlPreview);
        });

      sendBtn.addEventListener("click", sendRequest);
      autofillBtn.addEventListener("click", autofillFromEnv);
      clearBtn.addEventListener("click", clearResponse);
      bodyEl.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
          event.preventDefault();
          sendRequest();
        }
      });

      buildCurlPreview();
      loadOpenApiPresets();
    })();
  </script>
</body>
</html>
"""

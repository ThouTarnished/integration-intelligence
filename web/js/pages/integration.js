// Integration health: connection status, SLIs (latency percentiles, errors, throughput),
// a live API console and the self-describing endpoint catalog.
import { get, request } from "../core/api.js";
import { $, fmt, html, mount } from "../core/dom.js";
import { animate, countUp } from "../core/motion.js";
import { microBars, sparkline } from "../charts/sparkline.js";
import { jsonBlock, panel } from "../ui/components.js";
import { icon } from "../ui/icons.js";
import { toast } from "../ui/toast.js";

const SAMPLE = {
  user_id: "USR-1001", event_type: "login", ip_address: "198.51.100.23", location: "Lagos, Nigeria",
  device_id: "DEV-9123", failed_attempts: 4, ip_reputation: "suspicious", status: "failure",
};

const metric = (key, label, unit = "") => html`<section class="panel metric span-2" data-metric="${key}">
  <span class="eyebrow">${label}</span><div class="v"><span class="num" data-v>0</span>${unit ? html`<small>${unit}</small>` : ""}</div>
  <div class="spark" data-spark></div></section>`;

export default {
  title: "Integration",
  async render(view, ctx) {
    const [health, metrics] = await Promise.all([get("/integration/health"), get("/integration/metrics")]);
    const history = { requests: [], p50: [], p95: [], p99: [], errors: [] };
    let uptime = health.uptime_seconds;
    const endpoints = health.endpoints.filter((e) => !e.path.endsWith("/stream"));
    const byTag = endpoints.reduce((acc, e) => ((acc[e.tag] ||= []).push(e), acc), {});

    mount(view, html`
      <header class="page-head">
        <div><div class="eyebrow">Client integration</div><h1>Integration <em>health</em></h1>
          <p>What an integration team watches: is NovaBank connected, how fast and reliably do we answer, and how many events flow per minute.</p></div>
        <div class="page-actions"><a class="btn" href="/docs" target="_blank" rel="noopener">${icon("book", 14)}OpenAPI docs</a></div>
      </header>
      <div class="grid">${panel({ title: "Connection", idx: "01", cls: "span-12 ticks", body: html`
        <div class="hero-status"><div class="hero-orb"><i></i></div><div>
          <div class="eyebrow">${health.client} · ${health.integration}</div>
          <h2>${health.status === "CONNECTED" ? "Connected" : "Degraded"} <span class="dim" style="font-size:20px">· API ${health.api_health.toLowerCase()}</span></h2>
          <div class="hero-facts">
            <span>Uptime <b class="mono" data-uptime>${fmt.duration(uptime)}</b></span>
            <span>Version <b class="mono">${health.version}</b></span>
            <span>Events received <b class="mono" data-received>${fmt.num(health.events_received)}</b></span>
            <span>Last event <b>${fmt.ago(health.last_event)}</b></span>
            <span>AI analyst <b>${health.ai_mode}${health.ai_model ? ` · ${health.ai_model}` : ""}</b></span>
            <span>Rate limit <b class="mono">${health.rate_limit_per_minute}/min</b></span>
            <span>Live dashboards <b class="mono" data-clients>${health.live_clients}</b></span>
          </div></div></div>` })}</div>
      <div class="grid metrics-row">
        ${metric("requests", "API requests")}${metric("p50", "Latency p50", "ms")}${metric("p95", "Latency p95", "ms")}
        ${metric("p99", "Latency p99", "ms")}${metric("errors", "Error rate", "%")}${metric("ingest", "Ingested · 30 min")}
      </div>
      <div class="grid">
        ${panel({ title: "API console", idx: "02", cls: "span-7", tools: html`<button class="btn sm ghost" data-curl>${icon("copy", 13)}Copy as cURL</button>`, body: html`
          <div class="console">
            <div class="console-bar"><select class="select" data-method><option>POST</option><option>GET</option><option>PATCH</option></select>
              <input class="input" data-path value="/events" aria-label="Path under /api/v1">
              <button class="btn primary" data-send>${icon("send", 14)}Send</button></div>
            <textarea class="textarea" data-body rows="10" spellcheck="false" aria-label="Request body">${JSON.stringify(SAMPLE, null, 2)}</textarea>
            <div class="response-meta" data-meta><span class="dim">Response appears below. Write calls carry the X-API-Key header.</span></div>
            <div data-response></div>
          </div>` })}
        ${panel({ title: "Endpoint catalog", idx: "03", cls: "span-5", tools: html`<span class="tag">${endpoints.length} routes</span>`, body: html`
          <div class="catalog">${Object.entries(byTag).map(([tag, list]) => html`<div class="eyebrow" style="margin:10px 10px 4px">${tag}</div>
            ${list.map((e) => html`<div class="catalog-row" data-endpoint="${e.method} ${e.path}"><span class="method ${e.method}">${e.method}</span>
              <span class="path">${e.path.replace("/api/v1", "")}<small>${e.summary}</small></span>${e.auth ? icon("lock", 13) : ""}</div>`)}`)}</div>` })}
      </div>
      <div class="grid">${panel({ title: "Busiest routes", idx: "04", cls: "span-12", bodyCls: "flush", body: html`<div data-routes></div>` })}</div>`);

    const setMetrics = (m, first = false) => {
      const values = { requests: m.requests, p50: m.latency_ms.p50, p95: m.latency_ms.p95, p99: m.latency_ms.p99,
        errors: m.error_rate * 100, ingest: m.throughput_per_minute.reduce((a, b) => a + b, 0) };
      for (const [key, value] of Object.entries(values)) {
        const decimals = ["p50", "p95", "p99", "errors"].includes(key) ? 1 : 0;
        countUp(view.querySelector(`[data-metric="${key}"] [data-v]`), value, {
          duration: first ? 1100 : 600, format: (v) => (decimals ? v.toFixed(decimals) : fmt.num(v)),
        });
      }
      microBars(view.querySelector('[data-metric="ingest"] [data-spark]'), m.throughput_per_minute);
      for (const key of Object.keys(history)) {
        history[key].push(values[key]);
        if (history[key].length > 40) history[key].shift();
        if (history[key].length > 1) {
          sparkline(view.querySelector(`[data-metric="${key}"] [data-spark]`), history[key],
            { color: key === "errors" ? "--critical" : key === "requests" ? "--t3" : "--accent", animateIn: false });
        }
      }
      mount($("[data-routes]", view), html`<div class="table-wrap"><table class="table"><thead><tr><th>Route</th><th>Calls</th><th>Avg latency</th><th>4xx/5xx</th></tr></thead>
        <tbody>${m.routes.map((r) => html`<tr><td class="mono">${r.route}</td><td class="num mono">${fmt.num(r.count)}</td>
          <td class="num mono">${r.avg_ms.toFixed(1)} ms</td><td class="num mono ${r.errors ? "" : "faint"}">${r.errors}</td></tr>`)}</tbody></table></div>`);
      $("[data-clients]", view).textContent = m.live_clients;
    };
    setMetrics(metrics, true);

    ctx.every(1000, () => { uptime += 1; $("[data-uptime]", view).textContent = fmt.duration(uptime); });
    ctx.every(4000, async () => {
      setMetrics(await get("/integration/metrics"));
    });

    // --- console ---
    const methodEl = $("[data-method]", view), pathEl = $("[data-path]", view), bodyEl = $("[data-body]", view);
    view.addEventListener("click", (e) => {
      const row = e.target.closest("[data-endpoint]");
      if (!row) return;
      const [method, path] = row.dataset.endpoint.split(" ");
      methodEl.value = method;
      pathEl.value = path.replace("/api/v1", "").replace("{event_id}", "EVT-00001").replace("{incident_id}", "INC-0001")
        .replace("{user_id}", "USR-1001").replace("{scenario}", "brute_force");
      bodyEl.value = method === "GET" ? "" : path.endsWith("/events") ? JSON.stringify(SAMPLE, null, 2)
        : path.includes("incidents") ? JSON.stringify({ status: "INVESTIGATING" }, null, 2)
          : path.endsWith("/ask") ? JSON.stringify({ question: "Why was INC-0001 high risk?" }, null, 2)
            : path.endsWith("/evaluate") ? JSON.stringify({ signals: ["New device", "Suspicious IP"] }, null, 2) : "{}";
      animate(bodyEl, { opacity: [0.4, 1], duration: 400 });
    });

    $("[data-send]", view).addEventListener("click", async () => {
      const meta = $("[data-meta]", view), out = $("[data-response]", view);
      let body;
      if (methodEl.value !== "GET" && bodyEl.value.trim()) {
        try { body = JSON.parse(bodyEl.value); } catch { return toast({ title: "Body is not valid JSON", level: "HIGH" }); }
      }
      mount(meta, html`<span class="shimmer">Sending ${methodEl.value} ${pathEl.value}…</span>`);
      try {
        const r = await request(pathEl.value, { method: methodEl.value, body });
        mount(meta, html`<span class="http ${r.ok ? "ok" : "bad"}">${r.status}</span><span>${r.ms.toFixed(1)} ms round-trip</span>
          <span>server ${r.serverTime || "?"}</span><span>request-id ${r.requestId || "?"}</span>`);
        mount(out, jsonBlock(r.data));
        animate(out, { opacity: [0, 1], y: [6, 0], duration: 400, ease: "outExpo" });
      } catch (error) {
        mount(meta, html`<span class="http bad">ERR</span><span>${error.message}</span>`);
      }
    });

    $("[data-curl]", view).addEventListener("click", async () => {
      const auth = methodEl.value !== "GET" ? ' -H "X-API-Key: $IIP_API_KEY"' : "";
      const data = methodEl.value !== "GET" && bodyEl.value.trim() ? ` -H "Content-Type: application/json" -d '${bodyEl.value.replace(/\s+/g, " ")}'` : "";
      const curl = `curl -X ${methodEl.value} ${location.origin}/api/v1${pathEl.value}${auth}${data}`;
      try { await navigator.clipboard.writeText(curl); toast({ title: "cURL copied", body: curl.slice(0, 90) + (curl.length > 90 ? "…" : "") }); }
      catch { toast({ title: "Copy failed", body: "Clipboard access was blocked." }); }
    });

    ctx.on("live:event", () => {
      const el = $("[data-received]", view);
      if (el) el.textContent = fmt.num(Number(el.textContent.replace(/,/g, "")) + 1);
    });
  },
};

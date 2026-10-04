// Command center: KPIs, threat map, live feed, volume, score distribution, incidents, signals, customers.
import { get } from "../core/api.js";
import { $, fmt, html, mount, utc } from "../core/dom.js";
import { live, liveDotClass } from "../core/live.js";
import { animate, countUp, flip, stagger } from "../core/motion.js";
import { areaChart } from "../charts/area.js";
import { hbars } from "../charts/bars.js";
import { scoreHistogram } from "../charts/histogram.js";
import { sparkline } from "../charts/sparkline.js";
import { MAP_LEGEND, worldMap } from "../charts/worldmap.js";
import { avatar, bindSeg, empty, eventIcon, mitre, panel, seg, sev, status } from "../ui/components.js";
import { icon } from "../ui/icons.js";
import { openEvent, openIncident, openUser } from "../views/details.js";

const FEED_SIZE = 12;

const kpi = ({ key, label, iconName, value, foot = "", cls = "", extra = "" }) => html`
  <section class="panel kpi span-3" data-kpi="${key}">
    <div class="kpi-top"><span class="eyebrow">${label}</span>${icon(iconName, 15)}</div>
    <div class="kpi-value num ${cls}" data-count="${value}">0</div>
    <div class="kpi-foot">${foot}</div>${extra}
  </section>`;

const feedItem = (e, source = "") => html`
  <li class="feed-item lvl-${e.risk_level}" data-event="${e.event_id}">
    <span class="feed-icon">${eventIcon(e.event_type, 14)}</span>
    <div class="feed-main">
      <div><b>${fmt.type(e.event_type)}</b> · ${e.user_id} <span class="dim">${e.location}</span>${source ? html`<span class="source">${source}</span>` : ""}</div>
      <div class="feed-sub">${e.event_id} · ${fmt.time(e.timestamp)} · ${e.signals.length ? `${e.signals.length} signal${e.signals.length > 1 ? "s" : ""}` : "clean"}</div>
    </div>
    <span class="score-pill">${e.risk_score}</span>
  </li>`;

const incidentRow = (i) => html`<tr data-incident="${i.incident_id}">
  <td><div class="who"><span><b>${i.title}</b><small>${i.incident_id}</small></span></div></td>
  <td>${sev(i.severity)}</td><td>${i.user_name}</td><td class="num mono">${i.risk_score}</td>
  <td>${status(i.status)}</td><td class="dim">${fmt.ago(i.updated)}</td></tr>`;

const personRow = (u) => html`<div class="person-row" data-user="${u.user_id}">${avatar(u.name)}
  <div class="name">${u.name}<small>${u.user_id} · ${u.home_location}</small></div><span class="score-pill lvl-${u.risk_level}">${u.risk_score}</span></div>`;

function travelStats(geo) {
  const count = (kind) => geo.arcs.filter((a) => (a.impossible ? "impossible" : a.assessed === false ? "hostile" : "plausible") === kind).length;
  const fastest = Math.max(0, ...geo.arcs.filter((a) => a.impossible).map((a) => a.speed_kmh || 0));
  const stats = [
    ["Active cities", geo.cities.length, ""], ["Plausible trips", count("plausible"), ""],
    ["Unverified origins", count("hostile"), "lvl-HIGH"], ["Impossible routes", count("impossible"), "lvl-CRITICAL"],
    ["Fastest implied", fastest ? `${fmt.num(fastest)} km/h` : "—", fastest ? "lvl-CRITICAL" : ""],
  ];
  return html`<div class="map-stats">${stats.map(([label, value, cls]) => html`<div><small>${label}</small><b class="num ${cls}">${value}</b></div>`)}</div>`;
}

function hourLabels(generatedAt) {
  const now = utc(generatedAt);
  return Array.from({ length: 24 }, (_, i) => {
    const d = new Date(now.getTime() - (23 - i) * 3600e3);
    return `${String(d.getHours()).padStart(2, "0")}:00`;
  });
}

export default {
  title: "Overview",
  async render(view, ctx) {
    const s = await get("/dashboard/summary");
    const delta = s.events_prev_24h ? (s.events_24h - s.events_prev_24h) / s.events_prev_24h : 0;
    const open = s.incident_status.OPEN, investigating = s.incident_status.INVESTIGATING;
    const severities = Object.fromEntries(s.incident_severity.map((x) => [x.label, x.value]));
    const incidentTotal = Math.max(1, Object.values(severities).reduce((a, b) => a + b, 0));

    mount(view, html`
      <header class="page-head">
        <div><div class="eyebrow">NovaBank · identity &amp; risk events</div>
          <h1>Command <em>center</em></h1>
          <p>Every sign-in, payment and privileged action NovaBank sends us, scored by an explainable rule engine and correlated into incidents as it happens.</p></div>
        <div class="page-actions"><span class="updated mono dim" data-synced>synced ${fmt.time(s.generated_at)}</span>
          <a class="btn primary" href="#/simulation">${icon("zap", 14)}Simulate an attack</a></div>
      </header>

      <div class="grid">
        ${kpi({ key: "events", label: "Events · 24h", iconName: "activity", value: s.events_24h,
          foot: html`<span class="delta ${delta >= 0 ? "up" : "down"}">${delta >= 0 ? "▲" : "▼"} ${fmt.pct(Math.abs(delta))}</span> vs previous 24h`,
          extra: html`<div class="kpi-spark" data-spark="total"></div>` })}
        ${kpi({ key: "active", label: "Active incidents", iconName: "shield", value: s.active_incidents,
          foot: html`<span class="status OPEN">${open} open</span><span class="status INVESTIGATING">${investigating} investigating</span>`,
          extra: html`<div class="kpi-split"><i style="width:${(open / Math.max(1, open + investigating)) * 100}%;background:var(--critical)"></i><i style="flex:1;background:var(--medium)"></i></div>` })}
        ${kpi({ key: "high", label: "High-risk events", iconName: "alert", value: s.high_risk_events, cls: "lvl-HIGH",
          foot: html`${fmt.pct(s.high_risk_events / Math.max(1, s.total_events), 1)} of ${fmt.num(s.total_events)} events`,
          extra: html`<div class="kpi-spark" data-spark="risky"></div>` })}
        ${kpi({ key: "critical", label: "Critical incidents", iconName: "target", value: s.critical_incidents, cls: "lvl-CRITICAL",
          foot: "active · block & verify",
          extra: html`<div class="kpi-split">${["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((l) =>
            html`<i class="lvl-${l}" style="width:${((severities[l] || 0) / incidentTotal) * 100}%;background:var(--lvl)"></i>`)}</div>` })}
      </div>

      <div class="grid">
        ${panel({ title: "Global activity", idx: "01", cls: "span-8 ticks", tools: html`<span class="tag">${s.geo.cities.length} cities</span>`,
          body: html`<div data-map></div><div class="map-foot">${MAP_LEGEND()}</div>${travelStats(s.geo)}` })}
        ${panel({ title: "Live feed", idx: "02", cls: "span-4", bodyCls: "flush",
          tools: html`<span class="live-dot" data-live-dot></span>`,
          body: html`<ul class="feed" data-feed>${s.recent_events.slice(0, FEED_SIZE).map((e) => feedItem(e))}</ul>` })}
      </div>

      <div class="grid">
        ${panel({ title: "Event volume", idx: "03", cls: "span-8", tools: seg("range", [["24h", "24 hours"], ["7d", "7 days"]], "24h"),
          body: html`<div class="chart" data-volume></div>` })}
        ${panel({ title: "Score distribution", idx: "04", cls: "span-4", tools: html`<span class="tag">√ scale</span>`,
          body: html`<div class="chart" data-hist></div>` })}
      </div>

      <div class="grid">
        ${panel({ title: "Recent incidents", idx: "05", cls: "span-6", bodyCls: "flush",
          tools: html`<a class="btn sm ghost" href="#/incidents">Board ${icon("arrow", 13)}</a>`,
          body: s.recent_incidents.length ? html`<div class="table-wrap"><table class="table"><thead><tr><th>Incident</th><th>Severity</th>
            <th>Customer</th><th>Score</th><th>Status</th><th>Updated</th></tr></thead><tbody data-incidents>${s.recent_incidents.map(incidentRow)}</tbody></table></div>`
            : empty("No incidents yet. Run a scenario in the Simulation Center.") })}
        ${panel({ title: "Top signals", idx: "06", cls: "span-3", body: html`<div data-signals></div>` })}
        ${panel({ title: "Riskiest customers", idx: "07", cls: "span-3", bodyCls: "flush",
          body: html`<div class="people">${s.top_users.map(personRow)}</div>` })}
      </div>`);

    // --- motion & charts ---
    view.querySelectorAll("[data-count]").forEach((el, i) => countUp(el, Number(el.dataset.count), { delay: 200 + i * 90 }));
    animate(view.querySelectorAll(".kpi-split i"), { scaleX: [0, 1], duration: 1000, delay: stagger(60, { start: 500 }), ease: "outExpo" });
    sparkline($("[data-spark=total]", view), s.events_by_hour.map((h) => h.total), { color: "--t3" });
    sparkline($("[data-spark=risky]", view), s.events_by_hour.map((h) => h.risky), { color: "--high" });

    const map = worldMap($("[data-map]", view), s.geo, {
      onCity: (name) => { location.hash = `#/events?q=${encodeURIComponent(name.split(",")[0])}`; },
    });
    ctx.add(map.destroy);

    let stopVolume = null;
    const drawVolume = (range) => {
      stopVolume?.();
      const volume = $("[data-volume]", view);
      stopVolume = range === "24h"
        ? areaChart(volume, { labels: hourLabels(s.generated_at), series: [
          { key: "total", label: "All events", values: s.events_by_hour.map((h) => h.total), color: "--t2" },
          { key: "risky", label: "High & critical", values: s.events_by_hour.map((h) => h.risky), color: "--critical" }] })
        : areaChart(volume, { labels: s.events_by_day.map((d) => d.label), series: [
          { key: "total", label: "All events", values: s.events_by_day.map((d) => d.total), color: "--t2" },
          { key: "risky", label: "High & critical", values: s.events_by_day.map((d) => d.HIGH + d.CRITICAL), color: "--critical" }] });
    };
    drawVolume("24h");
    bindSeg(view, "range", drawVolume);
    ctx.add(() => stopVolume?.());
    ctx.add(scoreHistogram($("[data-hist]", view), s.score_histogram));

    hbars($("[data-signals]", view), s.top_signals.map((x) => ({
      label: x.label, value: x.value, level: x.weight >= 30 ? "HIGH" : x.weight >= 20 ? "MEDIUM" : "",
      meta: x.mitre ? mitre(x.mitre) : "",
    })));

    // --- interactions ---
    view.addEventListener("click", (e) => {
      const ev = e.target.closest("[data-event]"), inc = e.target.closest("[data-incident]"), usr = e.target.closest("[data-user]");
      if (ev) openEvent(ev.dataset.event);
      else if (inc) openIncident(inc.dataset.incident);
      else if (usr) openUser(usr.dataset.user);
    });

    // --- live updates ---
    const feed = $("[data-feed]", view);
    const counter = view.querySelector('[data-kpi="events"] .kpi-value');
    const highCounter = view.querySelector('[data-kpi="high"] .kpi-value');
    const dot = $("[data-live-dot]", view);
    const showLive = (state) => { dot.className = liveDotClass(state); };
    showLive(live.state);
    ctx.on("live:state", showLive);
    ctx.on("live:event", ({ event, source }) => {
      flip(feed, () => {
        feed.insertAdjacentHTML("afterbegin", String(feedItem(event, source)));
        while (feed.children.length > FEED_SIZE) feed.lastElementChild.remove();
      });
      animate(feed.firstElementChild, {
        opacity: [0, 1], x: [-12, 0], backgroundColor: ["rgba(62,230,209,0.16)", "rgba(62,230,209,0)"],
        duration: 1400, ease: "outExpo", onComplete: (a) => a.revert?.(),
      });
      map.ping(event);
      countUp(counter, Number(counter.dataset.value) + 1, { duration: 500 });
      if (event.risk_score >= 60) countUp(highCounter, Number(highCounter.dataset.value) + 1, { duration: 500 });
    });

    const refresh = async () => {
      const next = await get("/dashboard/summary");
      const synced = $("[data-synced]", view);
      if (!synced) return;
      synced.textContent = `synced ${fmt.time(next.generated_at)}`;
      countUp(view.querySelector('[data-kpi="active"] .kpi-value'), next.active_incidents, { duration: 700 });
      countUp(view.querySelector('[data-kpi="critical"] .kpi-value'), next.critical_incidents, { duration: 700 });
      countUp(counter, next.events_24h, { duration: 700 });
      countUp(highCounter, next.high_risk_events, { duration: 700 });
      const rows = $("[data-incidents]", view);
      if (rows) mount(rows, html`${next.recent_incidents.map(incidentRow)}`);
    };
    let pending = null;
    ctx.on("live:incident", () => { clearTimeout(pending); pending = setTimeout(refresh, 600); });
    ctx.on("incident:changed", refresh);
    ctx.on("live:resync", refresh);
    ctx.every(30000, refresh);
    ctx.add(() => clearTimeout(pending));
  },
};

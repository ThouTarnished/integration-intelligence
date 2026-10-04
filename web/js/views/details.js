// Detail drawers shared by every page: event, incident and customer.
import { get, patch, post } from "../core/api.js";
import { bus } from "../core/bus.js";
import { fmt, html, levelOf } from "../core/dom.js";
import { animate, enter } from "../core/motion.js";
import { hbars } from "../charts/bars.js";
import { gauge } from "../charts/gauge.js";
import { riskLine } from "../charts/riskline.js";
import { waterfall } from "../charts/waterfall.js";
import { avatar, bindSeg, eventIcon, jsonBlock, seg, sev, status } from "../ui/components.js";
import { openDrawer } from "../ui/drawer.js";
import { icon } from "../ui/icons.js";
import { toast } from "../ui/toast.js";

const AIRLINER_KMH = 900;

/** Vertical event timeline used by incidents, customers and the simulator. */
export function timelineList(events, { compact = false } = {}) {
  if (!events.length) return html`<div class="dim">No events.</div>`;
  return html`<ol class="timeline${compact ? " compact" : ""}"><i class="tl-line" aria-hidden="true"></i>${events.map((e) => html`
    <li class="lvl-${e.risk_level}" data-open-event="${e.event_id}" tabindex="0">
      <span class="tl-dot"></span>
      <time class="mono">${fmt.time(e.timestamp)}</time>
      <div class="tl-main">
        <div class="tl-title">${eventIcon(e.event_type, 13)}<b>${fmt.type(e.event_type)}</b>
          <span class="dim">${e.status === "failure" ? "failed" : ""}${e.transaction_amount ? fmt.money(e.transaction_amount) : ""}${e.resource_accessed || ""}</span></div>
        <div class="tl-sub">${e.location} · ${e.device_id}${e.device_new ? " (new)" : ""} · ${e.signals.join(", ") || "no signals"}</div>
      </div>
      <span class="score lvl-${e.risk_level} tl-score">${e.risk_score}</span>
    </li>`)}</ol>`;
}

function animateTimeline(root) {
  const line = root.querySelector(".tl-line");
  if (line) animate(line, { scaleY: [0, 1], duration: 900, ease: "outExpo" });
  enter(root.querySelectorAll(".timeline li"), { y: 6, step: 40, blur: 0, duration: 500, max: 20 });
}

function verdict(scoreValue, action, explanation, caption = "risk score") {
  return html`<section class="verdict lvl-${levelOf(scoreValue)}">
    <div class="verdict-gauge" data-gauge data-score="${scoreValue}" data-caption="${caption}"></div>
    <div class="verdict-text"><div class="eyebrow">Engine decision</div>
      <div class="verdict-action">${action}</div><p>${explanation}</p></div>
  </section>`;
}

function travelCard(trip) {
  if (!trip) return "";
  const speed = trip.speed_kmh ?? 0;
  const scaleMax = Math.max(AIRLINER_KMH * 2, speed * 1.1);
  const kind = trip.impossible ? "impossible" : trip.assessed ? "plausible" : "unjudged";
  const label = { impossible: "Impossible", plausible: "Plausible", unjudged: "Not judged · flagged IP or failed sign-in" }[kind];
  return html`<section class="drawer-section"><h4>Travel check</h4>
    <div class="travel ${kind}">
      <div class="travel-route"><span>${trip.from}</span><span class="travel-path">${icon("plane", 14)}</span><span>${trip.to}</span></div>
      <div class="travel-stats">
        <div><small>Distance</small><b class="num">${trip.distance_km == null ? "unknown" : `${fmt.num(trip.distance_km)} km`}</b></div>
        <div><small>Elapsed</small><b class="num">${fmt.duration(trip.minutes * 60)}</b></div>
        <div><small>Implied speed</small><b class="num">${trip.speed_kmh == null ? "unknown" : `${fmt.num(speed)} km/h`}</b></div>
        <div><small>Verdict</small><b>${label}</b></div>
      </div>
      ${trip.speed_kmh == null ? "" : html`<div class="speed-meter">
        <div class="speed-track"><i style="width:${Math.min(100, (speed / scaleMax) * 100)}%"></i>
          <span class="speed-limit" style="left:${(AIRLINER_KMH / scaleMax) * 100}%"><em>airliner · ${AIRLINER_KMH} km/h</em></span></div></div>`}
    </div></section>`;
}

function bindLinks(body) {
  const sheet = body.closest(".drawer-sheet"); // links live in the header badges as well as the body
  if (sheet.dataset.linked) return; // the sheet persists while the drawer is open: bind once, not once per view
  sheet.dataset.linked = "true";
  sheet.addEventListener("click", (e) => {
    const ev = e.target.closest("[data-open-event]");
    const inc = e.target.closest("[data-open-incident]");
    const usr = e.target.closest("[data-open-user]");
    if (ev) openEvent(ev.dataset.openEvent);
    else if (inc) openIncident(inc.dataset.openIncident);
    else if (usr) openUser(usr.dataset.openUser);
  });
}

function drawVerdict(body) {
  const el = body.querySelector("[data-gauge]");
  if (el) gauge(el, Number(el.dataset.score), { caption: el.dataset.caption, delay: 150 });
}

// ---------------------------------------------------------------- event
export function openEvent(id) {
  openDrawer(async () => {
    const e = await get(`/events/${id}`);
    const details = [
      ["Customer", html`<button class="link" data-open-user="${e.user_id}">${e.user_id}</button>`],
      ["Location", e.location], ["Device", `${e.device_id}${e.device_new ? " · first time seen" : ""}`],
      ["IP address", html`<span class="mono">${e.ip_address}</span> · ${e.ip_reputation}`],
      ["Outcome", `${e.status}${e.failed_attempts ? ` · ${e.failed_attempts} failed attempts` : ""}`],
      e.transaction_amount != null && ["Amount", fmt.money(e.transaction_amount)],
      e.resource_accessed && ["Resource", e.resource_accessed],
      ["Received", fmt.dateTime(e.timestamp)],
    ].filter(Boolean);
    return {
      eyebrow: `${fmt.type(e.event_type)} event`, title: e.event_id,
      badges: html`${sev(e.risk_level)}${e.incident_id ? html`<button class="chip" data-open-incident="${e.incident_id}">${icon("shield", 12)}${e.incident_id}</button>` : ""}`,
      body: html`${verdict(e.risk_score, e.recommended_action, e.explanation)}
        <section class="drawer-section"><h4>Why this score</h4><div data-waterfall></div></section>
        ${travelCard(e.context?.travel)}
        <section class="drawer-section"><h4>Event</h4><dl class="dl">${details.map(([k, v]) => html`<dt>${k}</dt><dd>${v}</dd>`)}</dl></section>
        <section class="drawer-section"><h4>Raw record</h4><details class="raw"><summary>Show JSON</summary>${jsonBlock(e)}</details></section>`,
      after(body) {
        drawVerdict(body);
        waterfall(body.querySelector("[data-waterfall]"), e.contributions || [], { total: e.risk_score });
        const bar = body.querySelector(".speed-track i");
        if (bar) animate(bar, { scaleX: [0, 1], duration: 1200, delay: 400, ease: "outExpo" });
        bindLinks(body);
      },
    };
  });
}

// ---------------------------------------------------------------- incident
export function openIncident(id) {
  openDrawer(async () => {
    const i = await get(`/incidents/${id}`);
    return {
      eyebrow: `${i.title} · ${i.event_count} correlated events`, title: i.incident_id,
      badges: html`${sev(i.severity)}${status(i.status)}`,
      body: html`
        <section class="triage">
          ${seg("status", [["OPEN", "Open"], ["INVESTIGATING", "Investigating"], ["RESOLVED", "Resolved"]], i.status)}
          <button class="btn sm" data-ask="${i.incident_id}">${icon("sparkles", 14)}Ask analyst</button>
        </section>
        ${verdict(i.risk_score, i.recommended_action, i.explanation, "peak score")}
        <section class="drawer-section"><h4>Signals &amp; ATT&amp;CK context</h4>
          <div class="chips">${i.signals.map((s) => html`<span class="chip">${s}</span>`)}</div>
          ${i.mitre.length ? html`<div class="chips" style="margin-top:10px">${i.mitre.map((m) => html`
            <a class="mitre" href="${m.url}" target="_blank" rel="noopener">${m.id}<span class="dim">${m.name}</span></a>`)}</div>` : ""}
        </section>
        ${i.user ? html`<section class="drawer-section"><h4>Affected customer</h4>
          <button class="person" data-open-user="${i.user.user_id}">${avatar(i.user.name, true)}
            <span><b>${i.user.name}</b><small class="mono">${i.user.user_id} · ${i.user.segment} · home ${i.user.home_location}</small></span>
            ${icon("chevron", 16)}</button></section>` : ""}
        <section class="drawer-section"><h4>Correlated timeline</h4>${timelineList(i.timeline)}</section>`,
      after(body) {
        drawVerdict(body);
        animateTimeline(body);
        bindLinks(body);
        bindSeg(body, "status", async (value) => {
          try {
            await patch(`/incidents/${i.incident_id}`, { status: value });
            const badge = body.closest(".drawer-sheet")?.querySelector(".drawer-head .status");
            if (badge) badge.outerHTML = String(status(value)); // keep the header's status badge in step
            toast({ title: `${i.incident_id} → ${value.toLowerCase()}`, body: i.title, level: i.severity });
            bus.emit("incident:changed", { incident_id: i.incident_id, status: value });
          } catch (error) {
            toast({ title: "Could not update incident", body: error.message, level: "CRITICAL" });
            return false; // bindSeg puts the control back on the saved status, ready for a retry
          }
        });
        body.querySelector("[data-ask]")?.addEventListener("click", () => bus.emit("analyst:ask", `Summarize ${i.incident_id}`));
      },
    };
  });
}

// ---------------------------------------------------------------- customer
export function openUser(id) {
  openDrawer(async () => {
    const [u, scenarios] = await Promise.all([get(`/users/${id}`), get("/simulation")]);
    return {
      eyebrow: `${u.segment} customer · home ${u.home_location}`, title: u.name,
      badges: html`${sev(u.risk.risk_level)}<span class="chip mono">${u.user_id}</span>`,
      body: html`${verdict(u.risk.risk_score, u.risk.recommended_action, u.risk.explanation, "current risk")}
        <section class="drawer-section"><h4>Risk over the last ${u.risk_history.length} events</h4><div data-riskline></div></section>
        <div class="two-col">
          <section class="drawer-section"><h4>Devices</h4><div class="device-list">${u.devices.map((d) => html`
            <div class="device ${d.trusted ? "trusted" : ""}">${icon("device", 14)}<span class="mono">${d.device_id}</span>
              <span class="tag ${d.trusted ? "accent" : ""}">${d.trusted ? "trusted" : "unknown"}</span><span class="dim num">${d.events} ev</span></div>`)}</div></section>
          <section class="drawer-section"><h4>Locations</h4><div data-locations></div></section>
        </div>
        <section class="drawer-section"><h4>Incidents</h4>${u.incidents.length ? html`<div class="mini-list">${u.incidents.map((i) => html`
          <button class="mini-row" data-open-incident="${i.incident_id}"><span class="mono dim">${i.incident_id}</span><b>${i.title}</b>
            ${sev(i.severity)}${status(i.status)}</button>`)}</div>` : html`<div class="dim">No incidents for this customer.</div>`}</section>
        <section class="drawer-section"><h4>Recent activity</h4>${timelineList(u.timeline.slice().reverse(), { compact: true })}</section>
        <section class="drawer-section"><h4>Simulate against this customer</h4>
          <div class="sim-inline"><select class="select" data-scenario>${scenarios.map((s) => html`<option value="${s.key}">${s.title}</option>`)}</select>
          <button class="btn sm primary" data-run>${icon("zap", 14)}Run scenario</button></div></section>`,
      after(body) {
        drawVerdict(body);
        const stopRiskLine = riskLine(body.querySelector("[data-riskline]"), u.risk_history);
        hbars(body.querySelector("[data-locations]"), u.locations.map((l) => ({
          label: l.location, value: l.events, meta: l.home ? html`<span class="tag">home</span>` : "",
          level: l.home ? "" : "HIGH",
        })));
        animateTimeline(body);
        bindLinks(body);
        body.querySelector("[data-run]").addEventListener("click", async (e) => {
          const button = e.currentTarget, scenario = body.querySelector("[data-scenario]").value;
          button.disabled = true;
          try {
            const result = await post(`/simulation/${scenario}?user_id=${encodeURIComponent(u.user_id)}`);
            toast({ title: `${result.scenario.title} replayed on ${u.name}`, body: `Peak score ${result.top_event.risk_score} · ${result.top_event.risk_level}`, level: result.top_event.risk_level });
            openUser(u.user_id);
          } catch (error) {
            toast({ title: "Simulation failed", body: error.message, level: "CRITICAL" });
            button.disabled = false;
          }
        });
        return stopRiskLine; // the drawer runs it when this view goes away, stopping the chart's resize observer
      },
    };
  });
}

/** Clicking any rendered reference (INC-0001, EVT-00001, USR-1001) opens its drawer. */
export function openRef(ref) {
  if (ref.startsWith("INC-")) openIncident(ref);
  else if (ref.startsWith("EVT-")) openEvent(ref);
  else if (ref.startsWith("USR-")) openUser(ref);
}

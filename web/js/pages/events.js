// Event explorer: search + filters + paging. New live events wait behind a "show" pill
// instead of shifting the table under the reader.
import { get } from "../core/api.js";
import { $, debounce, fmt, html, mount } from "../core/dom.js";
import { animate, enter } from "../core/motion.js";
import { bindSeg, empty, errorBox, eventIcon, panel, score, seg, signalChips, skeleton } from "../ui/components.js";
import { icon } from "../ui/icons.js";
import { openEvent, openIncident } from "../views/details.js";

const PAGE = 100;

const row = (e) => {
  const trip = e.context?.travel;
  return html`<tr data-event="${e.event_id}">
    <td class="id">${e.event_id}</td>
    <td class="dim">${fmt.dateTime(e.timestamp)}</td>
    <td class="mono">${e.user_id}</td>
    <td><span class="who">${eventIcon(e.event_type)}${fmt.type(e.event_type)}</span></td>
    <td>${e.location}${trip?.impossible ? html`<span class="travel-tag" title="Impossible travel">${icon("plane", 11)}${fmt.num(trip.speed_kmh)} km/h</span>` : ""}</td>
    <td>${score(e.risk_score, e.risk_level)}</td>
    <td>${signalChips(e.signals, 2)}</td>
    <td>${e.incident_id ? html`<button class="link" data-incident="${e.incident_id}">${e.incident_id}</button>` : html`<span class="faint">—</span>`}</td>
  </tr>`;
};

export default {
  title: "Events",
  async render(view, ctx, params) {
    const state = { q: params.get("q") || "", event_type: "", risk_level: (params.get("level") || "").toUpperCase(), sort: "desc", offset: 0 };
    let items = [], total = 0, pending = 0;

    mount(view, html`
      <header class="page-head">
        <div><div class="eyebrow">Ingestion log</div><h1>Events</h1>
          <p>Every event NovaBank has sent, with the engine's verdict. Click a row to see exactly why it scored what it did.</p></div>
        <div class="page-actions"><span class="tag" data-total>—</span></div>
      </header>
      <div class="filters">
        <label class="input-wrap">${icon("search", 15)}<input class="input" data-q placeholder="Search customer, name, IP, city, device…" value="${state.q}">
          <span class="kbd">/</span></label>
        ${seg("type", [["", "All"], ["login", "Logins"], ["transaction", "Payments"], ["resource_access", "Resources"], ["password_reset", "Resets"]], "")}
        ${seg("level", [["", "Any risk"], ["MEDIUM", "Medium"], ["HIGH", "High"], ["CRITICAL", "Critical"]], state.risk_level)}
        ${seg("sort", [["desc", "Newest"], ["asc", "Oldest"]], "desc")}
      </div>
      <div class="new-pill" data-new hidden><button>${icon("arrow", 13)}<span></span></button></div>
      ${panel({ title: "Results", idx: "", cls: "events-panel", bodyCls: "flush", body: html`<div data-table>${skeleton(8, 18)}</div>
        <div class="table-foot"><span data-shown></span><button class="btn sm" data-more hidden>Load ${PAGE} more</button></div>` })}`);

    const tableEl = $("[data-table]", view);
    let latest = 0; // ticket of the newest load
    const load = async (append = false) => {
      if (!append) state.offset = 0;
      const ticket = ++latest; // only the newest request may render
      try {
        const params = new URLSearchParams({ ...state, limit: PAGE });
        const page = await get(`/events?${params}`);
        if (ticket !== latest) return; // a newer search, filter or page took over
        total = page.total;
        items = append ? items.concat(page.items) : page.items;
        if (!append) {
          mount(tableEl, items.length ? html`<div class="table-wrap"><table class="table"><thead><tr><th>Event</th><th>Time</th><th>Customer</th>
            <th>Type</th><th>Location</th><th>Risk</th><th>Signals</th><th>Incident</th></tr></thead><tbody>${items.map(row)}</tbody></table></div>`
            : empty("No events match these filters.", "filter"));
          enter(tableEl.querySelectorAll("tbody tr"), { y: 6, step: 18, blur: 0, duration: 420, max: 24 });
        } else {
          const body = tableEl.querySelector("tbody");
          const before = body.children.length;
          body.insertAdjacentHTML("beforeend", String(html`${page.items.map(row)}`));
          enter([...body.children].slice(before), { y: 6, step: 14, blur: 0, max: 24 });
        }
        $("[data-total]", view).textContent = fmt.count(total, "event");
        $("[data-shown]", view).textContent = `Showing ${fmt.num(items.length)} of ${fmt.num(total)}`;
        $("[data-more]", view).hidden = items.length >= total;
      } catch (error) {
        if (ticket === latest) mount(tableEl, errorBox(error.message));
      }
    };

    const search = $("[data-q]", view);
    search.addEventListener("input", debounce(() => { state.q = search.value.trim(); load(); }, 220));
    bindSeg(view, "type", (v) => { state.event_type = v; load(); });
    bindSeg(view, "level", (v) => { state.risk_level = v; load(); });
    bindSeg(view, "sort", (v) => { state.sort = v; load(); });
    $("[data-more]", view).addEventListener("click", () => { state.offset += PAGE; load(true); });
    view.addEventListener("click", (e) => {
      const inc = e.target.closest("[data-incident]");
      if (inc) { e.stopPropagation(); openIncident(inc.dataset.incident); return; }
      const tr = e.target.closest("tr[data-event]");
      if (tr) openEvent(tr.dataset.event);
    });

    const pill = $("[data-new]", view);
    ctx.on("live:event", () => {
      pending += 1;
      pill.querySelector("span").textContent = `${pending} new event${pending > 1 ? "s" : ""} · show`;
      if (pill.hidden) {
        pill.hidden = false;
        animate(pill.querySelector("button"), { y: [-16, -4], opacity: [0, 1], duration: 500, ease: "outBack(1.6)" });
      }
    });
    pill.addEventListener("click", () => {
      pending = 0;
      pill.hidden = true;
      window.scrollTo({ top: 0, behavior: "smooth" });
      load();
    });

    ctx.focusSearch = () => search.focus();
    await load();
  },
};

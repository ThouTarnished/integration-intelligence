// Customers: a risk spectrum (every customer as a dot on the 0-100 scale) and a filterable table.
import { get } from "../core/api.js";
import { $, esc, fmt, html, mount } from "../core/dom.js";
import { animate, enter, stagger } from "../core/motion.js";
import { avatar, panel, score } from "../ui/components.js";
import { icon } from "../ui/icons.js";
import { hideTip, showTip } from "../ui/tooltip.js";
import { openUser } from "../views/details.js";

const row = (u) => html`<tr data-user="${u.user_id}">
  <td><div class="who">${avatar(u.name)}<span>${u.name}<small>${u.user_id}</small></span></div></td>
  <td class="dim">${u.segment}</td><td>${u.home_location}</td>
  <td>${score(u.risk_score, u.risk_level)}</td>
  <td class="num mono">${fmt.num(u.event_count)}</td>
  <td class="num mono">${u.open_incidents ? html`<span style="color:var(--critical)">${u.open_incidents}</span>` : html`<span class="faint">0</span>`}
    <span class="faint"> / ${u.incident_count}</span></td>
  <td class="dim">${fmt.ago(u.last_activity)}</td></tr>`;

export default {
  title: "Customers",
  async render(view) {
    const users = (await get("/users")).sort((a, b) => b.risk_score - a.risk_score || a.user_id.localeCompare(b.user_id));
    const elevated = users.filter((u) => u.risk_score >= 60).length;

    mount(view, html`
      <header class="page-head">
        <div><div class="eyebrow">Customer risk</div><h1>Customers</h1>
          <p>Each customer's current risk is the highest score among their ten most recent events, so one bad session stays visible until newer activity outweighs it.</p></div>
        <div class="page-actions"><span class="tag">${users.length} customers</span><span class="tag" style="color:var(--high)">${elevated} elevated</span></div>
      </header>
      <div class="grid">${panel({ title: "Risk spectrum", idx: "01", cls: "span-12", tools: html`<span class="dim" style="font-size:11.5px">hover a dot · click to open</span>`,
        body: html`<div class="spectrum"><div class="spectrum-inner" data-spectrum>
          <div class="spectrum-zones">${[["LOW", 30], ["MEDIUM", 30], ["HIGH", 20], ["CRITICAL", 20]].map(([l, w]) => html`<i class="lvl-${l}" style="width:${w}%"></i>`)}</div>
          <div class="spectrum-axis">${[0, 30, 60, 80, 100].map((t) => html`<span style="left:${t}%">${t}</span>`)}</div>
        </div></div>` })}</div>
      <div class="grid">${panel({ title: "All customers", idx: "02", cls: "span-12", bodyCls: "flush",
        tools: html`<label class="input-wrap" style="width:260px">${icon("search", 14)}<input class="input" data-filter placeholder="Filter by name, ID or city"></label>`,
        body: html`<div class="table-wrap"><table class="table"><thead><tr><th>Customer</th><th>Segment</th><th>Home</th><th>Risk</th>
          <th>Events</th><th>Open / all incidents</th><th>Last active</th></tr></thead><tbody data-rows>${users.map(row)}</tbody></table></div>` })}</div>`);

    // Spectrum: customers sharing a score stack upwards, five high, then wrap into a new column.
    const spectrum = $("[data-spectrum]", view);
    const stacks = {};
    for (const u of users) {
      const bucket = Math.round(u.risk_score / 3);
      const n = (stacks[bucket] = (stacks[bucket] || 0) + 1) - 1;
      spectrum.insertAdjacentHTML("beforeend", String(html`<button class="spectrum-dot lvl-${u.risk_level}" data-user="${u.user_id}"
        style="left:calc(${u.risk_score}% + ${Math.floor(n / 5) * 15}px);bottom:${34 + (n % 5) * 15}px" aria-label="${u.name}, risk ${u.risk_score}"></button>`));
    }
    animate(spectrum.querySelectorAll(".spectrum-dot"), { scale: [0, 1], opacity: [0, 1], duration: 700, ease: "outBack(2.2)", delay: stagger(25, { start: 250 }) });
    spectrum.addEventListener("pointermove", (e) => {
      const dot = e.target.closest(".spectrum-dot");
      if (!dot) return hideTip();
      const u = users.find((x) => x.user_id === dot.dataset.user);
      showTip(e.clientX, e.clientY, `<div class="tt-title">${esc(u.user_id)}</div><div><b>${esc(u.name)}</b></div>
        <div class="tt-row"><span>Risk</span><b>${u.risk_score} · ${esc(u.risk_level)}</b></div><div class="tt-row"><span>Home</span><b>${esc(u.home_location)}</b></div>`);
    });
    spectrum.addEventListener("pointerleave", hideTip);

    enter(view.querySelectorAll("[data-rows] tr"), { y: 6, step: 22, blur: 0, max: 25 });

    const rows = $("[data-rows]", view);
    $("[data-filter]", view).addEventListener("input", (e) => {
      const q = e.target.value.trim().toLowerCase();
      mount(rows, html`${users.filter((u) => !q || `${u.name} ${u.user_id} ${u.home_location}`.toLowerCase().includes(q)).map(row)}`);
    });
    view.addEventListener("click", (e) => {
      const target = e.target.closest("[data-user]");
      if (target) openUser(target.dataset.user);
    });
  },
};

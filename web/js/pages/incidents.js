// Incident triage board. Drag a card between columns (or use the drawer) to change status.
// The single most urgent card gets the animated border beam; everything else stays calm.
import { get, patch } from "../core/api.js";
import { bus } from "../core/bus.js";
import { $, $$, fmt, html, mount } from "../core/dom.js";
import { animate, enter, flipKeyed } from "../core/motion.js";
import { bindSeg, seg, sev } from "../ui/components.js";
import { icon } from "../ui/icons.js";
import { toast } from "../ui/toast.js";
import { openIncident } from "../views/details.js";

const COLUMNS = [
  ["OPEN", "Open", "New correlated incidents awaiting an analyst"],
  ["INVESTIGATING", "Investigating", "Being worked"],
  ["RESOLVED", "Resolved", "Closed out"],
];
const RESOLVED_SHOWN = 12;
const RANK = { CRITICAL: 3, HIGH: 2, MEDIUM: 1, LOW: 0 };

const card = (i) => html`<article class="inc-card lvl-${i.severity}" draggable="true" data-id="${i.incident_id}" data-severity="${i.severity}" tabindex="0">
  <div class="row">${sev(i.severity)}<span class="mono dim" style="font-size:11.5px">${i.incident_id}</span><span class="grip">${icon("grip", 14)}</span></div>
  <div class="title">${i.title}</div>
  <div class="meta"><span>${i.user_name}</span><span class="mono">score ${i.risk_score}</span><span>${fmt.count(i.event_count, "event")}</span><span style="margin-left:auto">${fmt.ago(i.updated)}</span></div>
</article>`;

export default {
  title: "Incidents",
  async render(view, ctx) {
    let incidents = await get("/incidents?limit=300");
    let filter = "";
    let showAllResolved = false;

    mount(view, html`
      <header class="page-head">
        <div><div class="eyebrow">Correlation engine output</div><h1>Incident <em>board</em></h1>
          <p>Related risky events for the same customer within 30 minutes are merged into one incident. Drag cards to triage them.</p></div>
        <div class="page-actions">${seg("sev", [["", "All"], ["CRITICAL", "Critical"], ["HIGH", "High"], ["MEDIUM", "Medium"]], "")}</div>
      </header>
      <div class="board">${COLUMNS.map(([key, label, hint]) => html`
        <section class="column" data-column="${key}">
          <header class="column-head"><span class="status ${key}">${label}</span><span class="dim" style="font-size:11.5px">${hint}</span><span class="count" data-count></span></header>
          <div class="column-body" data-body></div>
        </section>`)}</div>`);

    const draw = (animateCards = false) => {
      for (const [key] of COLUMNS) {
        const column = view.querySelector(`[data-column="${key}"]`);
        let list = incidents.filter((i) => i.status === key && (!filter || i.severity === filter));
        if (key !== "RESOLVED") list.sort((a, b) => RANK[b.severity] - RANK[a.severity] || b.risk_score - a.risk_score || b.updated.localeCompare(a.updated));
        const total = list.length;
        if (key === "RESOLVED" && !showAllResolved) list = list.slice(0, RESOLVED_SHOWN);
        $("[data-count]", column).textContent = total;
        mount($("[data-body]", column), html`${list.map(card)}${key === "RESOLVED" && total > list.length
          ? html`<button class="btn sm ghost more" data-more>Show ${total - list.length} more</button>` : ""}
          ${total ? "" : html`<div class="empty" style="padding:24px 8px">${icon("check", 18)}Nothing here</div>`}`);
      }
      const urgent = view.querySelector('[data-column="OPEN"] .inc-card[data-severity="CRITICAL"]');
      urgent?.insertAdjacentHTML("beforeend", '<span class="beam-ring" aria-hidden="true"></span>');
      if (animateCards) enter(view.querySelectorAll(".inc-card"), { y: 12, step: 30, max: 24 });
    };
    draw(true);

    bindSeg(view, "sev", (v) => { filter = v; draw(true); });

    const move = async (id, toStatus) => {
      const incident = incidents.find((i) => i.incident_id === id);
      if (!incident || incident.status === toStatus) return;
      const previous = incident.status;
      flipKeyed(view, ".inc-card", () => { incident.status = toStatus; draw(); });
      try {
        await patch(`/incidents/${id}`, { status: toStatus });
        toast({ title: `${id} → ${toStatus.toLowerCase()}`, body: incident.title, level: incident.severity });
      } catch (error) {
        incident.status = previous;
        draw();
        toast({ title: "Could not move incident", body: error.message, level: "CRITICAL" });
      }
    };

    // drag & drop
    let dragged = null;
    view.addEventListener("dragstart", (e) => {
      const el = e.target.closest(".inc-card");
      if (!el) return;
      dragged = el.dataset.id;
      el.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", dragged);
    });
    view.addEventListener("dragend", (e) => {
      e.target.closest(".inc-card")?.classList.remove("dragging");
      dragged = null; // a cancelled drag must not leave a card behind for the next drop
      $$(".column", view).forEach((c) => c.classList.remove("drop"));
    });
    view.addEventListener("dragover", (e) => {
      const column = e.target.closest(".column");
      if (!column || !dragged) return;
      e.preventDefault();
      $$(".column", view).forEach((c) => c.classList.toggle("drop", c === column));
    });
    view.addEventListener("drop", (e) => {
      const column = e.target.closest(".column");
      if (!column || !dragged) return;
      e.preventDefault();
      column.classList.remove("drop");
      move(dragged, column.dataset.column);
      dragged = null;
    });

    view.addEventListener("click", (e) => {
      if (e.target.closest("[data-more]")) { showAllResolved = true; draw(); return; }
      const el = e.target.closest(".inc-card");
      if (el) openIncident(el.dataset.id);
    });
    view.addEventListener("keydown", (e) => {
      const el = e.target.closest?.(".inc-card");
      if (el && e.key === "Enter") openIncident(el.dataset.id);
    });

    // live
    ctx.on("live:incident", (incoming) => {
      const index = incidents.findIndex((i) => i.incident_id === incoming.incident_id);
      flipKeyed(view, ".inc-card", () => {
        if (index >= 0) incidents[index] = { ...incidents[index], ...incoming };
        else incidents = [incoming, ...incidents];
        draw();
      });
      const el = view.querySelector(`.inc-card[data-id="${incoming.incident_id}"]`);
      if (el) animate(el, { boxShadow: ["0 0 0 2px rgba(62,230,209,.6)", "0 0 0 0 rgba(62,230,209,0)"], duration: 1600, ease: "outExpo", onComplete: (a) => a.revert?.() });
    });
    ctx.add(bus.on("incident:changed", ({ incident_id, status }) => {
      const incident = incidents.find((i) => i.incident_id === incident_id);
      if (incident && incident.status !== status) flipKeyed(view, ".inc-card", () => { incident.status = status; draw(); });
    }));
  },
};

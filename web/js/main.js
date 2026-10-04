// Application shell: router, navigation, keyboard shortcuts, live connection, global toasts.
import { get, post } from "./core/api.js";
import { bus } from "./core/bus.js";
import { $, $$, html, mount } from "./core/dom.js";
import { connectLive, live, liveDotClass } from "./core/live.js";
import { animate, enter, installSpotlight, set, spring } from "./core/motion.js";
import { askLater } from "./pages/analyst.js";
import { PAGES, SHORTCUTS } from "./pages/index.js";
import { boot } from "./ui/boot.js";
import { closeDrawer, drawerOpen, installDrawer } from "./ui/drawer.js";
import { askForKey, closePalette, installPalette, openPalette, paletteOpen } from "./ui/palette.js";
import { toast } from "./ui/toast.js";
import { hideTip } from "./ui/tooltip.js";
import { openIncident, openRef, openUser } from "./views/details.js";

// ------------------------------------------------------------------ router
let current = null, navToken = 0, currentName = "";

function createContext() {
  const cleanups = [];
  let disposed = false;
  const run = (fn) => { try { fn(); } catch (error) { console.warn(error); } };
  // A page may still be awaiting its data when the user leaves: whatever it registers after that runs at once.
  const keep = (fn) => (disposed ? run(fn) : cleanups.push(fn));
  return {
    on: (type, fn) => keep(bus.on(type, fn)),
    every: (ms, fn) => { if (!disposed) { const id = setInterval(fn, ms); cleanups.push(() => clearInterval(id)); } },
    add: (fn) => { if (typeof fn === "function") keep(fn); },
    dispose: () => { disposed = true; cleanups.splice(0).forEach(run); },
  };
}

function moveIndicator(link, instant = false) {
  const indicator = $(".nav-indicator");
  if (!link || !indicator) return;
  // Cover the link's whole box: the rail is a vertical list on wide screens but a horizontal bar on small ones.
  const target = { x: link.offsetLeft, y: link.offsetTop, width: link.offsetWidth, height: link.offsetHeight, opacity: 1 };
  if (instant) set(indicator, target);
  else animate(indicator, { ...target, ease: spring(0.2, 420) });
}

async function route() {
  const [path, query = ""] = location.hash.replace(/^#\/?/, "").split("?");
  const name = PAGES[path] ? path : "overview";
  const token = ++navToken;
  current?.dispose();
  hideTip(); // a chart tooltip belongs to the page being left
  const ctx = createContext();
  current = ctx;

  const link = $(`.nav a[data-page="${name}"]`);
  $$(".nav a").forEach((a) => a.classList.toggle("active", a === link));
  moveIndicator(link, !currentName);
  currentName = name;
  $("#crumb").textContent = PAGES[name].title;
  document.title = `${PAGES[name].title} · IIP`;

  const old = $("#view"), progress = $(".top-progress i");
  animate(progress, { scaleX: [0, 0.7], opacity: [1, 1], duration: 900, ease: "outExpo" });
  if (old.childElementCount) await animate(old, { opacity: [1, 0], y: [0, -8], duration: 150, ease: "in(2)" });
  if (token !== navToken) return;
  // Every page gets a fresh outlet, so listeners a page attached to it can never outlive the page.
  const view = old.cloneNode(false);
  view.removeAttribute("style");
  old.replaceWith(view);
  window.scrollTo(0, 0);
  try {
    await PAGES[name].render(view, ctx, new URLSearchParams(query));
  } catch (error) {
    mount(view, html`<div class="error-box">Could not load this page: ${error.message}</div>`);
  }
  animate(progress, { scaleX: 1, opacity: [1, 0], duration: 420, ease: "outExpo" });
  if (token !== navToken) return;
  enter(view.querySelectorAll(":scope > .page-head, :scope > .filters, :scope > .grid > *, :scope > .board > *"), { y: 16, step: 55, max: 14 });
}

// ------------------------------------------------------------------ actions shared with the palette
const actions = {
  openIncident, openUser,
  async toggleTraffic() {
    try {
      const status = await get("/simulation/traffic");
      const next = await post("/simulation/traffic", { enabled: !status.enabled });
      toast({ title: next.enabled ? "Live traffic started" : "Live traffic stopped", body: next.enabled ? "Events will stream in every few seconds." : "" });
    } catch (error) { toast({ title: "Could not toggle traffic", body: error.message, level: "CRITICAL" }); }
  },
};

// ------------------------------------------------------------------ chrome: clock, live state, traffic, counts
function startClock() {
  const el = $("#clock");
  const tick = () => {
    const now = new Date();
    el.innerHTML = String(html`${now.toISOString().slice(11, 19)} <span>UTC</span>`);
  };
  tick();
  setInterval(tick, 1000);
}

function renderLiveState(state) {
  const dot = $("#live-dot"), label = $("#live-label");
  dot.className = liveDotClass(state);
  label.textContent = { live: "Live", connecting: "Reconnecting", offline: "Offline" }[state];
}

async function refreshCounts() {
  try {
    const open = await get("/incidents?status=open&limit=500");
    const badge = $("#open-count");
    badge.textContent = open.length;
    badge.hidden = open.length === 0;
    return open;
  } catch { return []; }
}

function wireTraffic(initial) {
  const sw = $("#traffic-switch");
  sw.setAttribute("aria-checked", String(initial));
  sw.addEventListener("click", async () => {
    const enabled = sw.getAttribute("aria-checked") !== "true";
    sw.setAttribute("aria-checked", String(enabled));
    try { await post("/simulation/traffic", { enabled }); }
    catch (error) { sw.setAttribute("aria-checked", String(!enabled)); toast({ title: "Could not toggle traffic", body: error.message, level: "CRITICAL" }); }
  });
  bus.on("live:traffic", (status) => sw.setAttribute("aria-checked", String(status.enabled)));
}

// ------------------------------------------------------------------ keyboard
function installKeyboard() {
  let pendingG = 0;
  addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(actions); return; }
    if (e.key === "Escape") { if (paletteOpen()) closePalette(); else if (drawerOpen()) closeDrawer(); return; }
    // Timeline rows are focusable list items, not buttons: Enter or Space opens them like a click.
    if ((e.key === "Enter" || e.key === " ") && e.target.matches?.("[data-open-event]")) { e.preventDefault(); e.target.click(); return; }
    if (e.target.closest?.("input, textarea, select, [contenteditable]") || paletteOpen() || drawerOpen()) return;
    if (e.key === "/" && current?.focusSearch) { e.preventDefault(); current.focusSearch(); return; }
    if (e.key === "g") { pendingG = Date.now(); return; }
    if (Date.now() - pendingG < 900 && SHORTCUTS[e.key]) { location.hash = `#/${SHORTCUTS[e.key]}`; pendingG = 0; }
  });
}

// ------------------------------------------------------------------ live notifications
// Every incident that already exists, whatever its status, so only genuinely new ones are announced.
const knownIncidents = () => get("/incidents?limit=500").then((list) => list.map((i) => i.incident_id), () => []);

function installLiveToasts(knownIds) {
  let seen = new Set(knownIds), last = 0, recount = 0;
  bus.on("live:incident", (incident) => {
    // The server re-sends an incident on every change, so the badge is recounted (debounced) rather than bumped.
    clearTimeout(recount);
    recount = setTimeout(refreshCounts, 400);
    if (seen.has(incident.incident_id)) return;
    seen.add(incident.incident_id);
    if (currentName === "simulation" || Date.now() - last < 2500 || !["HIGH", "CRITICAL"].includes(incident.severity)) return;
    last = Date.now();
    toast({ title: `New ${incident.severity.toLowerCase()} incident · ${incident.incident_id}`, body: `${incident.title} · ${incident.user_name}`,
      level: incident.severity, onClick: () => openIncident(incident.incident_id) });
  });
  bus.on("live:reset", async () => {
    toast({ title: "Demo data was reset", body: "Reloading the current view." });
    seen = new Set(await knownIncidents()); // IDs start again from 1 after a reset
    refreshCounts();
    route();
  });
  bus.on("incident:changed", refreshCounts);
}

// ------------------------------------------------------------------ boot
async function main() {
  installDrawer();
  installPalette();
  installSpotlight();
  installKeyboard();
  startClock();
  connectLive();
  bus.on("live:state", renderLiveState);
  bus.on("live:resync", refreshCounts);
  bus.on("auth:required", () => askForKey(() => toast({ title: "Key saved. Retry your action." })));
  bus.on("analyst:ask", (question) => {
    closeDrawer();
    // Already on the Analyst page: hand the question over, so the conversation so far is kept.
    if (currentName === "analyst" && current?.ask) current.ask(question);
    else { askLater(question); location.hash = "#/analyst"; }
  });
  $("#search-trigger").addEventListener("click", () => openPalette(actions));
  if (/Mac|iPhone|iPad/.test(navigator.platform)) $("#search-trigger .kbd").textContent = "⌘ K";
  document.addEventListener("click", (e) => {
    const ref = e.target.closest("button.ref[data-ref]");
    if (ref && !e.defaultPrevented) openRef(ref.dataset.ref);
  });
  addEventListener("hashchange", route);
  // Keep the highlight on the active link when the nav changes size without a navigation (bottom-bar breakpoint, late fonts).
  new ResizeObserver(() => moveIndicator($(".nav a.active"), true)).observe($(".nav"));

  const [traffic, known] = await Promise.all([get("/simulation/traffic").catch(() => ({ enabled: false })),
    knownIncidents(), refreshCounts()]);
  wireTraffic(traffic.enabled);
  installLiveToasts(known);
  await boot();
  await route();
  renderLiveState(live.state);
  setInterval(refreshCounts, 30000);
}

main();

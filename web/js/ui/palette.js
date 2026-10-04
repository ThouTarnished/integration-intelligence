// Command palette (Ctrl/⌘+K): navigate, run scenarios, toggle settings, jump to any incident or customer.
import { get, post, setKey } from "../core/api.js";
import { $, html, mount, trapTab } from "../core/dom.js";
import { animate, motionEnabled, setMotion, spring, stagger } from "../core/motion.js";
import { icon } from "./icons.js";
import { toast } from "./toast.js";

let items = [], filtered = [], selected = 0, mode = "commands", onKey = null, generation = 0, lastFocus = null;
let cache = { at: 0, incidents: [], users: [], scenarios: [] };

const root = () => $("#palette");
export const paletteOpen = () => !root().hidden;

/** Subsequence match with a bonus for word starts. Returns 0 when there is no match. */
function score(text, query) {
  if (!query) return 1;
  text = text.toLowerCase();
  let s = 0, t = 0;
  for (const ch of query.toLowerCase()) {
    const found = text.indexOf(ch, t);
    if (found < 0) return 0;
    s += found === t ? 3 : found === 0 || text[found - 1] === " " ? 2 : 1;
    t = found + 1;
  }
  return s / text.length + s;
}

async function loadData() {
  if (Date.now() - cache.at < 15000) return;
  const [open, investigating, users, scenarios] = await Promise.all([
    get("/incidents?status=open&limit=40"), get("/incidents?status=investigating&limit=20"), get("/users"), get("/simulation")]);
  cache = { at: Date.now(), incidents: [...open, ...investigating], users, scenarios };
}

function build(actions) {
  const pages = [
    ["overview", "Overview", "overview", "G O"], ["events", "Events", "activity", "G E"], ["incidents", "Incidents", "shield", "G I"],
    ["users", "Customers", "users", "G C"], ["lab", "Risk Lab", "flask", "G L"], ["simulation", "Simulation", "zap", "G S"],
    ["integration", "Integration", "plug", "G N"], ["analyst", "AI Analyst", "sparkles", "G A"],
  ].map(([key, label, iconName, hint]) => ({ group: "Go to", label, iconName, hint, run: () => { location.hash = `#/${key}`; } }));
  const commands = [
    { group: "Actions", label: "Toggle live traffic", iconName: "radio", run: actions.toggleTraffic },
    { group: "Actions", label: motionEnabled() ? "Reduce motion" : "Enable motion", iconName: "wind", run: () => { setMotion(!motionEnabled()); toast({ title: motionEnabled() ? "Motion enabled" : "Motion reduced" }); } },
    { group: "Actions", label: "Open API documentation", iconName: "book", run: () => window.open("/docs", "_blank", "noopener") },
    { group: "Actions", label: "Reset demo data…", iconName: "refresh", hint: "Simulation", run: () => { location.hash = "#/simulation"; } },
  ];
  const scenarios = cache.scenarios.map((s) => ({ group: "Run scenario", label: s.title, iconName: "zap", hint: s.category, run: async () => {
    try {
      const r = await post(`/simulation/${s.key}`);
      toast({ title: `${s.title} replayed`, body: `${r.user.name} · peak ${r.top_event.risk_score} ${r.top_event.risk_level}`,
        level: r.top_event.risk_level, onClick: r.incident ? () => actions.openIncident(r.incident.incident_id) : undefined });
    } catch (error) { toast({ title: "Simulation failed", body: error.message, level: "CRITICAL" }); }
  } }));
  const incidents = cache.incidents.map((i) => ({ group: "Incidents", label: `${i.incident_id} · ${i.title}`, iconName: "shield",
    hint: `${i.severity.toLowerCase()} · ${i.user_name}`, run: () => actions.openIncident(i.incident_id) }));
  const users = cache.users.map((u) => ({ group: "Customers", label: `${u.name}`, iconName: "user",
    hint: `${u.user_id} · ${u.risk_score}`, run: () => actions.openUser(u.user_id) }));
  return [...pages, ...commands, ...scenarios, ...incidents, ...users];
}

function renderList(query) {
  const list = $(".palette-list", root());
  filtered = items.map((item) => ({ item, s: score(`${item.label} ${item.hint || ""} ${item.group}`, query) }))
    .filter((x) => x.s > 0).sort((a, b) => (query ? b.s - a.s : 0)).slice(0, 40).map((x) => x.item);
  selected = Math.min(selected, Math.max(0, filtered.length - 1));
  let group = null;
  mount(list, filtered.length ? html`${filtered.map((item, i) => {
    const header = item.group !== group ? html`<div class="palette-group eyebrow">${(group = item.group)}</div>` : "";
    return html`${header}<button class="palette-item" role="option" data-i="${i}" aria-selected="${String(i === selected)}">
      ${icon(item.iconName, 15)}<span>${item.label}</span>${item.hint ? html`<span class="hint">${item.hint}</span>` : ""}</button>`;
  })}` : html`<div class="empty" style="padding:28px">No matches</div>`);
}

function highlight() {
  root().querySelectorAll(".palette-item").forEach((el) => {
    const on = Number(el.dataset.i) === selected;
    el.setAttribute("aria-selected", String(on));
    if (on) el.scrollIntoView({ block: "nearest" });
  });
}

function frame(placeholder) {
  return html`<div class="palette-backdrop" data-close></div>
    <div class="palette-box" role="dialog" aria-modal="true" aria-label="Command palette">
      <div class="palette-input">${icon(mode === "key" ? "key" : "search", 17)}<input data-input placeholder="${placeholder}" autocomplete="off" spellcheck="false"
        ${mode === "key" ? "type=password" : ""}><span class="kbd">esc</span></div>
      <div class="palette-list" role="listbox"></div>
      <div class="palette-foot">${mode === "key" ? html`<span>Enter to save · stored for this browser session only</span>`
        : html`<span>↑↓ navigate</span><span>↵ select</span><span>esc close</span>`}</div>
    </div>`;
}

function show() {
  const el = root();
  generation += 1;
  if (el.hidden) lastFocus = document.activeElement; // where focus returns on close
  el.hidden = false;
  animate(el.querySelector(".palette-backdrop"), { opacity: [0, 1], duration: 200 });
  animate(el.querySelector(".palette-box"), { opacity: [0, 1], scale: [0.96, 1], y: [-10, 0], ease: spring(0.18, 380) });
  el.querySelector("[data-input]").focus();
}

export async function openPalette(actions) {
  if (paletteOpen()) return closePalette();
  mode = "commands";
  mount(root(), frame("Search pages, incidents, customers, scenarios…"));
  show();
  items = build(actions);
  renderList("");
  const opened = generation;
  try {
    await loadData();
    if (opened !== generation || mode !== "commands" || !paletteOpen()) return; // closed or replaced meanwhile
    items = build(actions);
    renderList(root().querySelector("[data-input]")?.value || "");
    animate(root().querySelectorAll(".palette-item"), { opacity: [0, 1], x: [-4, 0], duration: 260, delay: stagger(8) });
  } catch { /* palette still works for navigation */ }
}

/** Ask for the API key when the server is not in demo mode. */
export function askForKey(after) {
  mode = "key";
  onKey = after;
  mount(root(), frame("Paste the X-API-Key for write access"));
  mount($(".palette-list", root()), html`<div class="empty" style="padding:22px">${icon("lock", 18)}This action changes data, so it needs the integration API key.</div>`);
  show();
}

export async function closePalette() {
  const el = root();
  if (el.hidden) return;
  const opened = generation;
  await animate(el.querySelector(".palette-box"), { opacity: [1, 0], scale: [1, 0.97], duration: 140, ease: "in(2)" });
  if (opened !== generation) return; // re-opened meanwhile (e.g. the API-key prompt after a 401): leave it
  el.hidden = true;
  el.innerHTML = "";
  if (document.activeElement === document.body) lastFocus?.focus?.({ preventScroll: true });
}

export function installPalette() {
  const el = root();
  el.addEventListener("keydown", (e) => trapTab($(".palette-box", el), e));
  el.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) return closePalette();
    const item = e.target.closest(".palette-item");
    if (item) { const chosen = filtered[Number(item.dataset.i)]; closePalette(); chosen?.run(); }
  });
  el.addEventListener("input", (e) => { if (mode === "commands" && e.target.matches("[data-input]")) { selected = 0; renderList(e.target.value); } });
  el.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); closePalette(); return; }
    if (mode === "key") {
      if (e.key === "Enter" && e.target.value.trim()) { setKey(e.target.value); closePalette(); toast({ title: "API key saved for this session" }); onKey?.(); }
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      selected = (selected + (e.key === "ArrowDown" ? 1 : -1) + filtered.length) % Math.max(filtered.length, 1);
      highlight();
    } else if (e.key === "Enter" && filtered[selected]) {
      e.preventDefault();
      const chosen = filtered[selected];
      closePalette();
      chosen.run();
    }
  });
}

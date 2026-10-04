// Small, reusable HTML fragments. Each returns safe `html` output.
import { LEVELS, fmt, html, levelOf, raw } from "../core/dom.js";
import { movePill } from "../core/motion.js";
import { EVENT_ICONS, icon } from "./icons.js";

/** Severity: colour + 4-pip signal bar + text, so it never relies on colour alone. */
export function sev(level) {
  const lit = LEVELS.indexOf(level) + 1;
  const pips = [1, 2, 3, 4].map((i) => raw(`<i class="${i <= lit ? "on" : ""}"></i>`));
  return html`<span class="sev lvl-${level}"><span class="pips">${pips}</span>${level}</span>`;
}

export const status = (value) => html`<span class="status ${value}">${value}</span>`;

export function score(value, level = levelOf(value)) {
  return html`<span class="score lvl-${level}"><span class="num">${value}</span><span class="bar"><i style="width:${value}%"></i></span></span>`;
}

export function signalChips(signals = [], max = 3) {
  if (!signals.length) return html`<span class="faint">none</span>`;
  const shown = signals.slice(0, max).map((s) => html`<span class="chip">${s}</span>`);
  return html`<span class="chips">${shown}${signals.length > max ? html`<span class="chip">+${signals.length - max}</span>` : ""}</span>`;
}

export const mitre = (m) => (m ? html`<a class="mitre" href="${m.url}" target="_blank" rel="noopener" title="${m.name}">${m.id}</a>` : "");

export const avatar = (name, large = false) => html`<span class="avatar${large ? " lg" : ""}" aria-hidden="true">${fmt.initials(name)}</span>`;

export const eventIcon = (type, size = 14) => icon(EVENT_ICONS[type] || "activity", size);

export function panel({ title, idx = "", tools = "", body = "", cls = "", bodyCls = "" }) {
  return html`<section class="panel ${cls}">
    <header class="panel-head">${idx ? html`<span class="idx">${idx}</span>` : ""}<h3>${title}</h3><div class="tools">${tools}</div></header>
    <div class="panel-body ${bodyCls}">${body}</div>
  </section>`;
}

export const empty = (text, iconName = "layers") => html`<div class="empty">${icon(iconName, 22)}<div>${text}</div></div>`;

export const skeleton = (rows = 4, height = 14) =>
  html`<div style="display:grid;gap:10px">${Array.from({ length: rows }, (_, i) =>
    raw(`<div class="skeleton" style="height:${height}px;width:${92 - (i % 3) * 14}%"></div>`))}</div>`;

export const errorBox = (message) => html`<div class="error-box">${icon("alert", 14)} ${message}</div>`;

/** Segmented control. Wire it up with bindSeg after mounting. */
export function seg(name, options, value) {
  return html`<div class="seg" role="group" data-seg="${name}"><span class="pill"></span>${options.map(([v, label]) =>
    html`<button type="button" data-value="${v}" aria-pressed="${String(v === value)}">${label}</button>`)}</div>`;
}

export function bindSeg(root, name, onChange) {
  const el = root.querySelector(`[data-seg="${name}"]`);
  if (!el) return null;
  requestAnimationFrame(() => movePill(el, true));
  const select = (button) => {
    el.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
    movePill(el);
  };
  el.addEventListener("click", async (e) => {
    const button = e.target.closest("button");
    if (!button || button.getAttribute("aria-pressed") === "true") return;
    const previous = el.querySelector('[aria-pressed="true"]');
    select(button);
    // A handler that returns false (a failed save) puts the control back, so the change can simply be retried.
    if ((await onChange(button.dataset.value)) === false && previous) select(previous);
  });
  return el;
}
window.addEventListener("resize", () => document.querySelectorAll(".seg").forEach((el) => movePill(el, true)));

/** Pretty-printed, syntax-coloured JSON (escaped first, then tokens wrapped). */
export function jsonBlock(value) {
  const text = JSON.stringify(value, null, 2)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)/gi, (m, str, colon, bool, num) => {
      if (str) return colon ? `<span class="k">${str}</span><span class="p">${colon}</span>` : `<span class="s">${str}</span>`;
      if (bool) return `<span class="b">${bool}</span>`;
      return `<span class="n">${num}</span>`;
    });
  return raw(`<pre class="code">${text}</pre>`);
}

/** Minimal, safe markdown: escape everything, then allow **bold**, `code` and "- " bullets. */
export function markdown(text) {
  const escaped = String(text ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\b(INC-\d{4}|EVT-\d{5}|USR-\d{4})\b/g, '<button class="ref" data-ref="$1">$1</button>');
  const blocks = escaped.split(/\n{2,}/).map((block) => {
    const lines = block.split("\n");
    if (lines.every((l) => l.startsWith("- "))) return `<ul>${lines.map((l) => `<li>${inline(l.slice(2))}</li>`).join("")}</ul>`;
    const bullets = lines.findIndex((l) => l.startsWith("- "));
    if (bullets > 0) {
      return `<p>${lines.slice(0, bullets).map(inline).join("<br>")}</p><ul>${lines.slice(bullets)
        .map((l) => `<li>${inline(l.replace(/^- /, ""))}</li>`).join("")}</ul>`;
    }
    return `<p>${lines.map(inline).join("<br>")}</p>`;
  });
  return raw(blocks.join(""));
}

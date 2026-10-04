// Horizontal bar list (top signals, locations). Plain HTML, so labels stay real, accessible text.
import { fmt, html } from "../core/dom.js";
import { animate, stagger } from "../core/motion.js";

/** items: [{ label, value, meta?, level? }] */
export function hbars(el, items, { format = fmt.num } = {}) {
  const max = Math.max(1, ...items.map((i) => i.value));
  el.innerHTML = String(html`<div class="hbars">${items.map((item) => html`
    <div class="hbar ${item.level ? `lvl-${item.level}` : ""}">
      <div class="hbar-label"><span>${item.label}</span>${item.meta || ""}</div>
      <div class="hbar-track"><i style="width:${(item.value / max) * 100}%"></i></div>
      <div class="hbar-value num">${format(item.value)}</div>
    </div>`)}</div>`);
  animate(el.querySelectorAll(".hbar-track i"), { scaleX: [0, 1], duration: 900, ease: "outExpo", delay: stagger(55, { start: 120 }) });
}

// Tiny trend lines for KPI cards and metrics.
import { drawIn } from "../core/motion.js";
import { monotonePath, resolveColor, uid } from "./core.js";

export function sparkline(el, values, { color = "--t3", height = 34, fill = true, animateIn = true } = {}) {
  const W = el.clientWidth || 120, H = height, id = uid("spark");
  const stroke = resolveColor(color);
  const max = Math.max(1, ...values), n = Math.max(values.length - 1, 1);
  const pts = values.map((v, i) => [(i / n) * (W - 4) + 2, H - 3 - (v / max) * (H - 8)]);
  const line = monotonePath(pts);
  el.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" aria-hidden="true">
    <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${stroke}" stop-opacity=".25"/>
      <stop offset="1" stop-color="${stroke}" stop-opacity="0"/></linearGradient></defs>
    ${fill ? `<path d="${line}L${pts[pts.length - 1][0]},${H}L${pts[0][0]},${H}Z" fill="url(#${id})"/>` : ""}
    <path class="spark-line" d="${line}" fill="none" stroke="${stroke}" stroke-width="1.5" stroke-linejoin="round"/>
    <circle cx="${pts[pts.length - 1][0]}" cy="${pts[pts.length - 1][1]}" r="2.5" fill="${stroke}"/>
  </svg>`;
  if (animateIn) drawIn(el.querySelector(".spark-line"), { duration: 1300, ease: "inOutQuad" });
}

/** Vertical bars for small integer series (e.g. events per minute). */
export function microBars(el, values, { color = "--accent", height = 46 } = {}) {
  const max = Math.max(1, ...values), fillColor = resolveColor(color);
  const W = el.clientWidth || 200, gap = 2, bw = (W - gap * (values.length - 1)) / values.length;
  el.innerHTML = `<svg width="${W}" height="${height}" viewBox="0 0 ${W} ${height}" aria-hidden="true">${values.map((v, i) => {
    const h = v ? Math.max(2, (v / max) * (height - 2)) : 1;
    return `<rect x="${i * (bw + gap)}" y="${height - h}" width="${bw}" height="${h}" rx="1" fill="${fillColor}" opacity="${v ? 0.85 : 0.18}"/>`;
  }).join("")}</svg>`;
}

// A customer's risk over their recent events, drawn over the engine's level bands.
import { esc, fmt } from "../core/dom.js";
import { clipReveal } from "../core/motion.js";
import { hideTip, showTip } from "../ui/tooltip.js";
import { LEVEL_COLORS, cssVar, linear, monotonePath, responsive, uid } from "./core.js";

export function riskLine(el, points, { height = 170 } = {}) {
  const id = uid("risk");
  return responsive(el, (W, animateIn) => {
    const colors = LEVEL_COLORS();
    const pad = { top: 10, right: 10, bottom: 20, left: 28 };
    const iw = W - pad.left - pad.right, ih = height - pad.top - pad.bottom;
    const x = linear(0, Math.max(points.length - 1, 1), pad.left, pad.left + iw);
    const y = linear(0, 100, pad.top + ih, pad.top);
    const bands = [[0, 30, "LOW"], [30, 60, "MEDIUM"], [60, 80, "HIGH"], [80, 100, "CRITICAL"]];
    const line = monotonePath(points.map((p, i) => [x(i), y(p.risk_score)]));
    el.innerHTML = `<svg width="${W}" height="${height}" viewBox="0 0 ${W} ${height}" role="img" aria-label="Risk score history">
      <defs><clipPath id="${id}"><rect x="0" y="0" width="${W}" height="${height}"/></clipPath></defs>
      ${bands.map(([a, b, lvl]) => `<rect x="${pad.left}" width="${iw}" y="${y(b)}" height="${y(a) - y(b)}" fill="${colors[lvl]}" opacity=".055"/>
        <text class="axis" x="${pad.left - 6}" y="${y(a) - 2}" text-anchor="end">${a}</text>`).join("")}
      <g clip-path="url(#${id})"><path d="${line}" fill="none" stroke="${cssVar("--t2")}" stroke-width="1.5"/>
        ${points.map((p, i) => `<circle data-i="${i}" cx="${x(i)}" cy="${y(p.risk_score)}" r="${p.risk_score >= 60 ? 4 : 3}"
          fill="${colors[p.risk_level]}" stroke="${cssVar("--s1")}" stroke-width="1.5"/>`).join("")}</g>
      <text class="axis" x="${pad.left}" y="${height - 4}">older</text><text class="axis" x="${W - pad.right}" y="${height - 4}" text-anchor="end">latest</text>
    </svg>`;
    const svg = el.querySelector("svg");
    svg.addEventListener("pointermove", (e) => {
      const dot = e.target.closest("circle[data-i]");
      if (!dot) return hideTip();
      const p = points[dot.dataset.i];
      showTip(e.clientX, e.clientY, `<div class="tt-title">${esc(p.event_id)} · ${fmt.dateTime(p.timestamp)}</div>
        <div class="tt-row"><span>Score</span><b>${p.risk_score}</b></div><div class="tt-row"><span>Level</span><b>${esc(p.risk_level)}</b></div>`);
    });
    svg.addEventListener("pointerleave", hideTip);
    if (animateIn) clipReveal(svg.querySelector(`#${id} rect`), W, { duration: 1100 });
  });
}

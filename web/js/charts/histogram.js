// Score distribution: one bar per possible score (weights are multiples of 5), coloured by the
// level that score falls in, with the engine's thresholds marked. √ scale so the long tail shows.
import { esc, fmt } from "../core/dom.js";
import { animate, stagger } from "../core/motion.js";
import { hideTip, showTip } from "../ui/tooltip.js";
import { responsive } from "./core.js";

export function scoreHistogram(el, buckets, { height = 210, thresholds = [30, 60, 80] } = {}) {
  return responsive(el, (W, animateIn) => {
    const pad = { top: 22, right: 6, bottom: 24, left: 6 };
    const iw = W - pad.left - pad.right, ih = height - pad.top - pad.bottom;
    const band = iw / buckets.length;
    const max = Math.sqrt(Math.max(1, ...buckets.map((b) => b.value)));
    const base = pad.top + ih;
    const xOf = (score) => pad.left + (score / 5) * band;

    const bars = buckets.map((b, i) => {
      const h = b.value ? Math.max(2, (Math.sqrt(b.value) / max) * ih) : 0;
      return `<rect class="bar lvl-${b.level}" data-i="${i}" x="${pad.left + i * band + band * 0.18}" width="${band * 0.64}"
        y="${base - h}" height="${h}" rx="1.5" data-h="${h}"/>`;
    });
    const marks = thresholds.map((t) => `<g class="threshold"><line x1="${xOf(t)}" x2="${xOf(t)}" y1="${pad.top - 8}" y2="${base}"/>
      <text x="${xOf(t) + 4}" y="${pad.top - 10}">${t}</text></g>`);

    el.innerHTML = `<svg class="hist" width="${W}" height="${height}" viewBox="0 0 ${W} ${height}" role="img" aria-label="Distribution of event risk scores">
      <line x1="${pad.left}" x2="${W - pad.right}" y1="${base}" y2="${base}" class="baseline"/>
      ${marks.join("")}${bars.join("")}
      ${[0, 25, 50, 75, 100].map((s) => `<text class="axis" x="${xOf(s) + band / 2}" y="${height - 7}" text-anchor="middle">${s}</text>`).join("")}
    </svg>`;

    const svg = el.querySelector("svg");
    svg.addEventListener("pointermove", (e) => {
      const rect = e.target.closest("rect.bar");
      if (!rect) return hideTip();
      const b = buckets[rect.dataset.i];
      showTip(e.clientX, e.clientY, `<div class="tt-title">Score ${b.score}</div>
        <div class="tt-row"><span>Events</span><b>${fmt.num(b.value)}</b></div><div class="tt-row"><span>Level</span><b>${esc(b.level)}</b></div>`);
    });
    svg.addEventListener("pointerleave", hideTip);

    if (animateIn) {
      const rects = [...svg.querySelectorAll("rect.bar")];
      animate(rects, {
        height: (r) => [0, Number(r.dataset.h)],
        y: (r) => [base, base - Number(r.dataset.h)],
        duration: 900, ease: "outExpo", delay: stagger(22, { start: 150 }),
      });
    }
  });
}

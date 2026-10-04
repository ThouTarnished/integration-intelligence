// Area chart: neutral total volume with the high-risk share drawn in risk colour on top.
// Clip-path reveal on first draw, snapping crosshair + tooltip on hover.
import { esc, fmt } from "../core/dom.js";
import { animate, clipReveal } from "../core/motion.js";
import { hideTip, showTip } from "../ui/tooltip.js";
import { cssVar, fadeMask, linear, monotonePath, niceMax, resolveColor, responsive, uid } from "./core.js";

/**
 * @param {HTMLElement} el
 * @param {{labels: string[], series: {key: string, label: string, values: number[], color: string}[], height?: number}} data
 */
export function areaChart(el, { labels, series, height = 220 }) {
  const id = uid("area");
  series = series.map((s) => ({ ...s, color: resolveColor(s.color) }));
  return responsive(el, (W, animateIn) => {
    const pad = { top: 14, right: 10, bottom: 26, left: 36 };
    const H = height, iw = W - pad.left - pad.right, ih = H - pad.top - pad.bottom;
    const max = niceMax(Math.max(1, ...series.flatMap((s) => s.values)));
    const x = linear(0, labels.length - 1, pad.left, pad.left + iw);
    const y = linear(0, max, pad.top + ih, pad.top);
    const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => t * max);
    const every = Math.ceil(labels.length / Math.max(2, Math.floor(iw / 64)));

    const paths = series.map((s, si) => {
      const pts = s.values.map((v, i) => [x(i), y(v)]);
      const line = monotonePath(pts);
      const area = `${line}L${x(labels.length - 1)},${y(0)}L${x(0)},${y(0)}Z`;
      return `<linearGradient id="${id}-f${si}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="${s.color}" stop-opacity="${si ? 0.32 : 0.22}"/><stop offset="1" stop-color="${s.color}" stop-opacity="0"/></linearGradient>
        <path d="${area}" fill="url(#${id}-f${si})"/>
        <path d="${line}" fill="none" stroke="${s.color}" stroke-width="${si ? 1.8 : 1.6}" stroke-linejoin="round"/>`;
    });

    el.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(series.map((s) => s.label).join(" and "))} over time">
      <defs>${fadeMask(`${id}-m`, W, H)}<clipPath id="${id}-c"><rect x="0" y="0" width="${W}" height="${H}"/></clipPath></defs>
      <g mask="url(#${id}-m)">${ticks.map((t) => `<line x1="${pad.left}" x2="${W - pad.right}" y1="${y(t)}" y2="${y(t)}" stroke="rgb(255 255 255 / .07)" stroke-dasharray="3 4"/>`).join("")}</g>
      ${ticks.map((t) => `<text x="${pad.left - 8}" y="${y(t) + 3.5}" text-anchor="end" class="axis">${fmt.num(t)}</text>`).join("")}
      ${labels.map((l, i) => {
        const last = i === labels.length - 1;
        if (i % every !== 0 && !last) return "";
        const anchor = i === 0 ? "start" : last ? "end" : "middle";
        return `<text x="${x(i)}" y="${H - 7}" text-anchor="${anchor}" class="axis">${esc(l)}</text>`;
      }).join("")}
      <g clip-path="url(#${id}-c)">${paths.join("")}</g>
      <g class="crosshair" opacity="0"><line y1="${pad.top}" y2="${pad.top + ih}" stroke="rgb(255 255 255 / .28)"/>
        ${series.map((s) => `<circle r="4" fill="${s.color}" stroke="${cssVar("--s1")}" stroke-width="2"/>`).join("")}</g>
      <rect class="hit" x="${pad.left}" y="${pad.top}" width="${iw}" height="${ih}" fill="transparent"/>
    </svg>`;

    const svg = el.querySelector("svg");
    const cross = svg.querySelector(".crosshair");
    const dots = [...cross.querySelectorAll("circle")];
    const hit = svg.querySelector(".hit");
    let shown = -1;
    hit.addEventListener("pointermove", (e) => {
      const r = svg.getBoundingClientRect();
      const i = Math.max(0, Math.min(labels.length - 1, Math.round(((e.clientX - r.left - pad.left) / iw) * (labels.length - 1))));
      if (i !== shown) {
        shown = i;
        cross.setAttribute("opacity", "1");
        cross.querySelector("line").setAttribute("x1", x(i));
        cross.querySelector("line").setAttribute("x2", x(i));
        dots.forEach((d, si) => { d.setAttribute("cx", x(i)); d.setAttribute("cy", y(series[si].values[i])); });
      }
      showTip(e.clientX, e.clientY, `<div class="tt-title">${esc(labels[i])}</div>${series.map((s) =>
        `<div class="tt-row"><span style="color:${s.color}">${esc(s.label)}</span><b>${fmt.num(s.values[i])}</b></div>`).join("")}`);
    });
    hit.addEventListener("pointerleave", () => { shown = -1; cross.setAttribute("opacity", "0"); hideTip(); });

    if (animateIn) {
      clipReveal(svg.querySelector(`#${id}-c rect`), W, { duration: 1200 });
      animate(svg.querySelectorAll("text.axis"), { opacity: [0, 1], duration: 600, delay: 300 });
    }
  });
}

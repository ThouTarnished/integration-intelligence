// Semicircle risk gauge. One animated value drives the arc, the riding dot, the number and the
// colour, so the arc visibly changes level (slate -> amber -> orange -> red) as it climbs.
import { levelOf } from "../core/dom.js";
import { animate, motionEnabled } from "../core/motion.js";

const CX = 110, CY = 108, R = 88;
const point = (f) => {
  const theta = Math.PI * (1 - f);
  return [CX + R * Math.cos(theta), CY - R * Math.sin(theta)];
};
const arc = (f0, f1) => {
  const [x0, y0] = point(f0), [x1, y1] = point(f1);
  return `M${x0.toFixed(2)},${y0.toFixed(2)} A${R},${R} 0 0 1 ${x1.toFixed(2)},${y1.toFixed(2)}`;
};
const ZONES = [[0, 0.3, "LOW"], [0.3, 0.6, "MEDIUM"], [0.6, 0.8, "HIGH"], [0.8, 1, "CRITICAL"]];

export function gauge(el, score, { caption = "risk score", delay = 0, from = 0 } = {}) {
  const ticks = [0, 30, 60, 80, 100].map((t) => {
    const [x0, y0] = point(t / 100);
    const nx = (x0 - CX) / R, ny = (y0 - CY) / R;
    return `<line class="tick" x1="${x0 + nx * 10}" y1="${y0 + ny * 10}" x2="${x0 + nx * 16}" y2="${y0 + ny * 16}"/>
      <text class="tick-label" x="${x0 + nx * 26}" y="${y0 + ny * 26 + 3}" text-anchor="middle">${t}</text>`;
  }).join("");
  el.innerHTML = `<div class="gauge">
    <svg viewBox="0 0 220 124" role="img" aria-label="Risk score ${score} out of 100">
      <path class="track" d="${arc(0, 1)}"/>
      ${ZONES.map(([a, b, lvl]) => `<path class="zone lvl-${lvl}" d="${arc(a + 0.004, b - 0.004)}"/>`).join("")}
      ${ticks}
      <path class="value lvl-LOW" d="${arc(0, 1)}" pathLength="100" stroke-dasharray="0 100"/>
      <circle class="knob lvl-LOW" r="6" cx="${point(0)[0]}" cy="${point(0)[1]}"/>
    </svg>
    <div class="gauge-readout"><div class="gauge-num num">0</div><div class="gauge-cap">${caption}</div></div>
  </div>`;

  const value = el.querySelector(".value"), knob = el.querySelector(".knob"), num = el.querySelector(".gauge-num");
  const render = (v) => {
    const level = `lvl-${levelOf(Math.round(v))}`;
    value.setAttribute("stroke-dasharray", `${v} 100`);
    const [x, y] = point(v / 100);
    knob.setAttribute("cx", x);
    knob.setAttribute("cy", y);
    if (!value.classList.contains(level)) {
      value.setAttribute("class", `value ${level}`);
      knob.setAttribute("class", `knob ${level}`);
    }
    num.textContent = Math.round(v);
  };
  const state = { v: from };
  render(from);
  if (!motionEnabled()) return render(score);
  animate(state, { v: score, duration: 1400, delay, ease: "outExpo", onUpdate: () => render(state.v) });
}

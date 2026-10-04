// Score waterfall: how each signal moves the running total, then the clamped final score.
// This is the visual answer to "why did this score X?".
import { html, levelOf, raw } from "../core/dom.js";
import { animate, motionEnabled, set, timeline } from "../core/motion.js";
import { mitre } from "../ui/components.js";

/** contributions: [{ signal, weight, detail, mitre }] (heaviest first, negatives last) */
export function waterfall(el, contributions, { total, showDetail = true } = {}) {
  let running = 0;
  const steps = contributions.map((c) => {
    const start = running;
    running += c.weight;
    return { ...c, start, end: running };
  });
  const lo = Math.min(0, ...steps.map((s) => Math.min(s.start, s.end)));
  const hi = Math.max(100, ...steps.map((s) => Math.max(s.start, s.end)));
  const pct = (v) => ((v - lo) / (hi - lo)) * 100;
  const final = total ?? Math.max(0, Math.min(100, running));
  const clamped = running !== final;

  const rows = steps.map((s) => {
    const negative = s.weight < 0;
    const left = pct(Math.min(s.start, s.end)), width = Math.max(0.6, pct(Math.max(s.start, s.end)) - left);
    const level = negative ? "LOW" : levelOf(Math.max(0, s.end));
    return html`<div class="wf-row">
      <div class="wf-label"><b>${s.signal}</b>${showDetail && s.detail ? html`<small>${s.detail}</small>` : ""}</div>
      <div class="wf-track"><i class="wf-bar lvl-${level}${negative ? " neg" : ""}" style="left:${left}%;width:${width}%"></i></div>
      <div class="wf-weight ${negative ? "neg" : ""}">${negative ? "" : "+"}${s.weight}${s.mitre ? raw(" ") : ""}${mitre(s.mitre)}</div>
    </div>`;
  });
  const level = levelOf(final);

  el.innerHTML = String(html`<div class="waterfall">
    <div class="wf-rows">${rows.length ? rows : html`<div class="dim" style="padding:8px 0">No signals raised. The event matches the customer's baseline.</div>`}</div>
    <div class="wf-row wf-total">
      <div class="wf-label"><b>Risk score</b><small>${clamped ? `sum ${running}, clamped to 0–100` : "sum of weights"}</small></div>
      <div class="wf-track"><i class="wf-bar lvl-${level}" style="left:${pct(0)}%;width:${pct(final) - pct(0)}%"></i></div>
      <div class="wf-weight lvl-${level}"><span class="wf-final num">${final}</span></div>
    </div>
  </div>`);

  if (!motionEnabled()) return;
  set(el.querySelectorAll(".wf-row"), { opacity: 0 });
  set(el.querySelectorAll(".wf-bar"), { scaleX: 0 });
  const tl = timeline({ defaults: { ease: "outExpo" } });
  el.querySelectorAll(".wf-rows .wf-row").forEach((row, i) => {
    tl.add(row, { opacity: [0, 1], x: [-8, 0], duration: 380 }, i ? "-=260" : 0)
      .add(row.querySelector(".wf-bar"), { scaleX: [0, 1], duration: 620 }, "-=300");
  });
  tl.add(el.querySelector(".wf-total"), { opacity: [0, 1], duration: 300 }, "-=200")
    .add(el.querySelector(".wf-total .wf-bar"), { scaleX: [0, 1], duration: 900 }, "-=200");
  const num = el.querySelector(".wf-final"), state = { v: 0 };
  animate(state, { v: final, duration: 1000, delay: 160 + steps.length * 140, ease: "outExpo",
    onUpdate: () => { num.textContent = Math.round(state.v); } });
}

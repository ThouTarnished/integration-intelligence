// Risk Lab: toggle signals and watch the real engine (POST /risk/evaluate) score them.
// Nothing is stored; it is the rulebook made tangible.
import { post, get } from "../core/api.js";
import { $, $$, debounce, fmt, html, mount } from "../core/dom.js";
import { animate, enter, stagger } from "../core/motion.js";
import { gauge } from "../charts/gauge.js";
import { waterfall } from "../charts/waterfall.js";
import { mitre, panel, sev } from "../ui/components.js";
import { icon } from "../ui/icons.js";

const PRESETS = [
  ["Clean login", ["Trusted device"]],
  ["Business traveller", ["Unusual location", "Trusted device"]],
  ["New phone abroad", ["New device", "Unusual location"]],
  ["Credential attack", ["Multiple failed login attempts", "Suspicious IP", "New device", "Unusual location"]],
  ["Card testing", ["Rapid transactions", "Suspicious IP", "Unusual location", "Suspicious transaction"]],
  ["Account takeover", ["Impossible travel", "Suspicious IP", "New device", "Privileged resource access", "Suspicious transaction"]],
];

export default {
  title: "Risk Lab",
  async render(view) {
    const rules = await get("/risk/rules");
    const selected = new Set(["New device", "Unusual location"]);
    const t = rules.thresholds;

    mount(view, html`
      <header class="page-head">
        <div><div class="eyebrow">Explainable scoring</div><h1>Risk <em>lab</em></h1>
          <p>The engine is a transparent sum of weighted signals, clamped to 0–100. Toggle signals to see exactly how a score, its level and the recommended action are derived.</p></div>
      </header>
      <div class="grid">
        <div class="span-7">
          <div class="lab-presets">${PRESETS.map(([name]) => html`<button class="btn sm" data-preset="${name}">${name}</button>`)}
            <button class="btn sm ghost" data-preset="">Clear</button></div>
          <div class="lab-signals">${rules.signals.map((s) => html`
            <button class="signal-card" data-signal="${s.name}" aria-pressed="${String(selected.has(s.name))}">
              <div class="top"><span class="check">${icon("check", 11)}</span><span class="name">${s.name}</span>
                <span class="weight ${s.weight < 0 ? "neg" : ""}">${s.weight > 0 ? "+" : ""}${s.weight}</span></div>
              <p>${s.description}</p>${s.mitre ? html`<div>${mitre(s.mitre)}</div>` : ""}
            </button>`)}</div>
        </div>
        <div class="span-5"><div class="lab-result">${panel({ title: "Engine output", idx: "", cls: "ticks", body: html`
          <div data-gauge></div>
          <div style="display:flex;justify-content:center;margin:6px 0 14px" data-level></div>
          <div data-waterfall></div>
          <div class="formula" data-formula></div>` })}</div></div>
      </div>
      <div class="grid">${panel({ title: "Levels & actions", idx: "01", cls: "span-6", body: html`
        <div class="levels-ruler">${rules.levels.map((l) => html`<div class="lvl-${l.level}"><b>${l.level} · ${l.min_score}+</b>${l.action}</div>`)}</div>` })}
        ${panel({ title: "Detection thresholds", idx: "02", cls: "span-6", body: html`<div class="spec">
          <div><small>Failed attempts</small><b>≥ ${t.failed_attempts}</b></div>
          <div><small>Impossible travel</small><b>&gt; ${fmt.num(t.impossible_travel.speed_kmh)} km/h</b></div>
          <div><small>Min. distance judged</small><b>${fmt.num(t.impossible_travel.min_distance_km)} km</b></div>
          <div><small>Rapid transactions</small><b>${t.rapid_transactions.count} in ${t.rapid_transactions.window_minutes} min</b></div>
          <div><small>Password spray</small><b>${t.password_spray.accounts} accts / ${t.password_spray.window_minutes} min</b></div>
          <div><small>Large transaction</small><b>${fmt.money(t.large_transaction)}</b></div>
          <div><small>Incident opens at</small><b>${t.incident.open}+</b></div>
          <div><small>Correlation window</small><b>${t.incident.window_minutes} min</b></div>
        </div>` })}</div>`);

    let previous = 0, latest = 0;
    const evaluate = async () => {
      const ticket = ++latest;
      const result = await post("/risk/evaluate", { signals: [...selected] });
      if (ticket !== latest) return; // a newer selection is already being scored
      gauge($("[data-gauge]", view), result.risk_score, { from: previous });
      previous = result.risk_score;
      mount($("[data-level]", view), sev(result.risk_level));
      waterfall($("[data-waterfall]", view), result.contributions, { total: result.risk_score, showDetail: false });
      const parts = result.contributions.map((c) => (c.weight < 0 ? `− ${-c.weight}` : `${c.weight}`));
      const sum = result.contributions.reduce((acc, c) => acc + c.weight, 0);
      mount($("[data-formula]", view), html`${parts.length ? parts.join(" + ").replace(/\+ −/g, "−") : "0"} = <b>${sum}</b>
        ${sum !== result.risk_score ? html` → clamp → <b>${result.risk_score}</b>` : ""} → <span class="lvl lvl-${result.risk_level}">${result.risk_level}</span>
        · ${result.recommended_action}`);
    };
    const refresh = debounce(evaluate, 90);

    const sync = () => $$("[data-signal]", view).forEach((card) => card.setAttribute("aria-pressed", String(selected.has(card.dataset.signal))));
    view.addEventListener("click", (e) => {
      const card = e.target.closest("[data-signal]");
      if (card && !e.target.closest(".mitre")) {
        const name = card.dataset.signal;
        selected.has(name) ? selected.delete(name) : selected.add(name);
        sync();
        animate(card, { scale: [0.97, 1], duration: 380, ease: "outBack(2)" });
        refresh();
      }
      const preset = e.target.closest("[data-preset]");
      if (preset) {
        selected.clear();
        (PRESETS.find(([n]) => n === preset.dataset.preset)?.[1] || []).forEach((s) => selected.add(s));
        sync();
        animate($$('[data-signal][aria-pressed="true"]', view), { scale: [0.94, 1], duration: 500, ease: "outBack(2)", delay: stagger(40) });
        refresh();
      }
    });

    enter(view.querySelectorAll(".signal-card"), { y: 10, step: 35, max: 12 });
    await evaluate();
  },
};

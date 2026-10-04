// Simulation Center: replay a scenario through the real pipeline and watch each stage light up.
import { get, post } from "../core/api.js";
import { $, $$, fmt, html, mount, sleep } from "../core/dom.js";
import { animate, enter, motionEnabled, typeText } from "../core/motion.js";
import { gauge } from "../charts/gauge.js";
import { waterfall } from "../charts/waterfall.js";
import { empty, panel, sev } from "../ui/components.js";
import { icon } from "../ui/icons.js";
import { toast } from "../ui/toast.js";
import { openEvent, openIncident, timelineList } from "../views/details.js";

const STAGES = [
  ["ingest", "Ingest", "send"], ["normalize", "Normalize", "filter"], ["enrich", "Enrich", "globe"],
  ["score", "Score", "gauge"], ["correlate", "Correlate", "layers"], ["publish", "Publish", "radio"],
];

/** Hold-to-confirm: the action fires only after the button is held for `ms`. */
function holdButton(button, ms, onConfirm) {
  let timer = null;
  const start = (e) => {
    if (e.type === "keydown" && e.key !== " " && e.key !== "Enter") return;
    if (timer) return;
    e.preventDefault();
    button.setAttribute("data-holding", "");
    timer = setTimeout(() => { cancel(); onConfirm(); }, ms);
  };
  const cancel = () => { clearTimeout(timer); timer = null; button.removeAttribute("data-holding"); };
  button.addEventListener("pointerdown", start);
  button.addEventListener("keydown", start);
  ["pointerup", "pointerleave", "keyup", "blur"].forEach((type) => button.addEventListener(type, cancel));
}

export default {
  title: "Simulation",
  async render(view, ctx) {
    const [scenarios, traffic, users] = await Promise.all([get("/simulation"), get("/simulation/traffic"), get("/users")]);
    let generated = traffic.generated;

    mount(view, html`
      <header class="page-head">
        <div><div class="eyebrow">Simulation center</div><h1>Replay an <em>attack</em></h1>
          <p>Scenarios are not mocked: their events go through the same ingestion pipeline as a real NovaBank call, are stored in SQLite and stream to every open dashboard.</p></div>
      </header>
      <div class="grid">
        ${panel({ title: "Scenarios", idx: "01", cls: "span-8", tools: html`<select class="select" data-target style="height:28px;font-size:12px">
            <option value="">Random customer</option>${users.map((u) => html`<option value="${u.user_id}">${u.name} · ${u.user_id}</option>`)}</select>`,
          body: html`<div class="scenarios">${scenarios.map((s) => html`
            <button class="scenario" data-scenario="${s.key}"><span><span class="tag ${s.category}">${s.category}</span></span>
              <span class="title">${s.title}</span><p>${s.summary}</p></button>`)}</div>` })}
        ${panel({ title: "Controls", idx: "02", cls: "span-4", body: html`
          <div class="control-row"><div><b>Live traffic</b><small>Background generator: steady activity with the occasional attack.</small></div>
            <button class="switch" role="switch" aria-checked="${String(traffic.enabled)}" data-traffic aria-label="Live traffic"></button></div>
          <div class="control-row"><div><b>Events generated</b><small>by the live generator this session</small></div>
            <span class="mono num" data-generated style="font-size:18px">${fmt.num(generated)}</span></div>
          <div class="control-row"><div><b>Reset demo data</b><small>Wipe and re-seed a fresh synthetic week. Hold to confirm.</small></div>
            <button class="btn sm danger hold" data-reset><span>${icon("refresh", 13)}</span><span>Hold</span></button></div>` })}
      </div>
      <div class="grid">${panel({ title: "Pipeline", idx: "03", cls: "span-12 ticks", tools: html`<span class="dim" data-run-label style="font-size:12px">Pick a scenario to run</span>`,
        body: html`<div class="pipeline">${STAGES.map(([key, name, iconName]) => html`
          <div class="stage" data-stage="${key}"><div class="stage-node">${icon(iconName, 20)}</div><div class="stage-name">${name}</div>
            <div class="stage-detail" data-detail></div><div class="pipe"><span class="packet"></span></div></div>`)}</div>` })}</div>
      <div class="grid" data-results>${panel({ title: "Result", idx: "04", cls: "span-12", body: empty("Results appear here after a run.", "zap") })}</div>`);

    const resetStages = () => $$(".stage", view).forEach((stage) => {
      stage.classList.remove("active", "done");
      $("[data-detail]", stage).textContent = "";
      $(".pipe", stage).classList.remove("lit");
    });

    const animateStages = async (steps) => {
      for (const [i, step] of steps.entries()) {
        const stage = view.querySelector(`[data-stage="${step.stage}"]`);
        if (!stage) continue;
        stage.classList.add("active");
        animate($(".stage-node", stage), { scale: [0.86, 1], duration: 600, ease: "outBack(2.4)" });
        await typeText($("[data-detail]", stage), step.detail, { speed: 9 });
        stage.classList.replace("active", "done");
        if (i < steps.length - 1) {
          const pipe = $(".pipe", stage);
          pipe.classList.add("lit");
          if (motionEnabled()) {
            await animate($(".packet", stage), { left: ["0%", "100%"], opacity: [0, 1, 1, 0], duration: 420, ease: "inOutSine" });
          }
        }
        await sleep(motionEnabled() ? 60 : 0);
      }
    };

    const showResult = (r) => {
      const top = r.top_event;
      mount($("[data-results]", view), html`
        ${panel({ title: "Peak event", idx: "04", cls: "span-4 ticks", body: html`<div data-gauge></div>
          <div style="display:flex;justify-content:center;gap:8px;margin:8px 0 12px">${sev(top.risk_level)}<span class="chip mono">${top.event_id}</span></div>
          <p class="muted" style="margin:0;font-size:12.5px;text-align:center">${top.recommended_action}</p>
          ${r.incident ? html`<div class="result-cta"><div><div class="eyebrow">Incident</div><b>${r.incident.incident_id} · ${r.incident.title}</b>
            ${r.incident_ids.length > 1 ? html`<small class="dim"> +${r.incident_ids.length - 1} more</small>` : ""}</div>
            <button class="btn sm primary" data-open-incident="${r.incident.incident_id}">Open ${icon("arrow", 13)}</button></div>`
            : html`<div class="result-cta"><div class="dim">Below the incident threshold: no incident opened.</div></div>`}` })}
        ${panel({ title: "Why it scored this", idx: "05", cls: "span-8", body: html`<div data-waterfall></div>` })}
        ${panel({ title: `Generated events · ${r.events.length}`, idx: "06", cls: "span-12", tools: html`<span class="dim" style="font-size:12px">${r.affected_users.length} customer(s) affected</span>`,
          body: timelineList(r.events, { compact: true }) })}`);
      enter($$("[data-results] > .panel", view), { step: 90 });
      gauge($("[data-gauge]", view), top.risk_score, { caption: "peak score", delay: 200 });
      waterfall($("[data-waterfall]", view), top.contributions, { total: top.risk_score });
    };

    view.addEventListener("click", async (e) => {
      const incident = e.target.closest("[data-open-incident]");
      if (incident) return openIncident(incident.dataset.openIncident);
      const row = e.target.closest("[data-open-event]");
      if (row) return openEvent(row.dataset.openEvent);
      const button = e.target.closest("[data-scenario]");
      if (!button) return;
      const cards = $$("[data-scenario]", view);
      cards.forEach((c) => { c.disabled = true; });
      button.classList.add("running");
      resetStages();
      const label = $("[data-run-label]", view);
      label.textContent = `Running ${button.querySelector(".title").textContent}…`;
      label.classList.add("shimmer");
      try {
        const target = $("[data-target]", view).value;
        const result = await post(`/simulation/${button.dataset.scenario}${target ? `?user_id=${target}` : ""}`);
        label.textContent = `${result.scenario.title} · ${result.user.name}`;
        label.classList.remove("shimmer");
        await animateStages(result.steps);
        showResult(result);
      } catch (error) {
        label.classList.remove("shimmer");
        label.textContent = "Run failed";
        toast({ title: "Simulation failed", body: error.message, level: "CRITICAL" });
      } finally {
        cards.forEach((c) => { c.disabled = false; });
        button.classList.remove("running");
      }
    });

    const trafficSwitch = $("[data-traffic]", view);
    trafficSwitch.addEventListener("click", async () => {
      const enabled = trafficSwitch.getAttribute("aria-checked") !== "true";
      trafficSwitch.setAttribute("aria-checked", String(enabled));
      try {
        await post("/simulation/traffic", { enabled });
      } catch (error) {
        trafficSwitch.setAttribute("aria-checked", String(!enabled));
        toast({ title: "Could not toggle traffic", body: error.message, level: "CRITICAL" });
      }
    });
    ctx.on("live:traffic", (status) => trafficSwitch.setAttribute("aria-checked", String(status.enabled)));
    ctx.on("live:event", ({ source }) => {
      if (source !== "traffic") return;
      generated += 1;
      $("[data-generated]", view).textContent = fmt.num(generated);
    });

    holdButton($("[data-reset]", view), 1200, async () => {
      try {
        await post("/simulation/reset");
        toast({ title: "Demo data reset", body: "A fresh synthetic week has been seeded." });
      } catch (error) {
        toast({ title: "Reset failed", body: error.message, level: "CRITICAL" });
      }
    });

    enter(view.querySelectorAll(".scenario"), { y: 12, step: 40 });
  },
};

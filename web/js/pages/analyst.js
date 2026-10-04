// AI Analyst chat. The engine's deterministic decision is shown separately from the
// language-model (or deterministic) explanation, so it is always clear who decided what.
import { get, post } from "../core/api.js";
import { $, html, mount } from "../core/dom.js";
import { animate, enter, motionEnabled } from "../core/motion.js";
import { markdown, panel, sev } from "../ui/components.js";
import { icon } from "../ui/icons.js";

const SUGGESTIONS = [
  "Which incidents are most urgent right now?",
  "Show impossible travel incidents",
  "Which customers logged in from Lagos?",
  "Why was this incident considered high risk?",
  "What is password spray?",
  "Summarize the last 24 hours",
];
const THINKING = ["Gathering context from the database…", "Consulting the rule engine…", "Composing an explanation…"];
let queued = null; // question handed over from another page ("Ask analyst")

export const askLater = (question) => { queued = question; };

export default {
  title: "AI Analyst",
  async render(view, ctx) {
    const health = await get("/integration/health");
    mount(view, html`
      <header class="page-head">
        <div><div class="eyebrow">Explanations, not decisions</div><h1>AI <em>analyst</em></h1>
          <p>Ask in plain words. Name a record (INC-0001, EVT-00042, USR-1001 or a customer's name), an attack, a place, a risk level, a status or a time window such as "last 24 hours"; every answer shows how it read the question.</p></div>
        <div class="page-actions"><span class="tag accent">${health.ai_mode}${health.ai_model ? ` · ${health.ai_model}` : ""}</span></div>
      </header>
      <div class="grid">
        <div class="span-8 chat">
          <div class="suggestions">${SUGGESTIONS.map((q) => html`<button data-q="${q}">${q}</button>`)}</div>
          <div class="thread" data-thread aria-live="polite"></div>
          <form class="composer" data-form><input data-input placeholder="Ask about an incident, a customer or a signal…" autocomplete="off" maxlength="500">
            <button class="btn primary" type="submit">${icon("send", 14)}Ask</button></form>
        </div>
        <div class="span-4">${panel({ title: "How the analyst works", idx: "", body: html`<div class="how">
          <div class="how-step"><span>1</span><div><b>Retrieve</b>Plain rules turn your question into search terms (IDs, names, signals, places, levels, statuses, time windows), and only the matching records are pulled from SQLite.</div></div>
          <div class="how-step"><span>2</span><div><b>Decide</b>The rule engine's score is attached unchanged. The model can't alter it.</div></div>
          <div class="how-step"><span>3</span><div><b>Explain</b>${health.ai_mode === "openai" ? "The OpenAI model explains the decision from that context alone." : "No API key is set, so a deterministic analyst writes the explanation from the same context. It works fully offline."}</div></div>
          <div class="how-step"><span>4</span><div><b>Cite</b>Every answer lists the records it used. Click one to open it.</div></div>
        </div>` })}</div>
      </div>`);

    const thread = $("[data-thread]", view), input = $("[data-input]", view);

    const ask = async (question) => {
      if (!question.trim()) return;
      input.value = "";
      thread.insertAdjacentHTML("beforeend", String(html`<div class="msg user"><div class="bubble">${question}</div></div>`));
      enter(thread.lastElementChild, { y: 8, blur: 0 });
      thread.insertAdjacentHTML("beforeend", String(html`<div class="msg bot"><div class="msg-head">${icon("sparkles", 13)}Analyst</div>
        <div class="bubble"><span class="shimmer" data-thinking>${THINKING[0]}</span></div></div>`));
      const bot = thread.lastElementChild;
      enter(bot, { y: 8, blur: 0 });
      bot.scrollIntoView({ behavior: motionEnabled() ? "smooth" : "auto", block: "end" });
      let step = 0;
      const ticker = setInterval(() => { const t = bot.querySelector("[data-thinking]"); if (t) t.textContent = THINKING[++step % THINKING.length]; }, 900);
      try {
        const [r] = await Promise.all([post("/ai/ask", { question }), new Promise((ok) => setTimeout(ok, motionEnabled() ? 700 : 0))]);
        clearInterval(ticker);
        const d = r.decision;
        mount(bot.querySelector(".bubble"), html`
          ${d ? html`<div class="decision lvl-${d.risk_level}"><span class="big">${d.risk_score}</span>
            <div><b>${d.subject}</b> ${sev(d.risk_level)}<small>Engine decision · ${d.recommended_action}</small></div>
            <span class="tag">deterministic</span></div>` : ""}
          <div class="answer">${markdown(r.explanation)}</div>
          <div class="msg-head" style="margin-top:12px">${r.source === "openai" ? `OpenAI · ${r.model}` : "Deterministic analyst"}
            ${r.sources.length ? html` · sources ${r.sources.map((s) => html`<button class="ref" data-ref="${s}">${s}</button>`)}` : ""}</div>
          ${r.note ? html`<div class="dim" style="font-size:12px;margin-top:6px">${r.note}</div>` : ""}`);
        const blocks = bot.querySelectorAll(".decision, .answer > *, .bubble > .msg-head");
        animate(blocks, { opacity: [0, 1], y: [6, 0], duration: 500, ease: "outExpo", delay: (_, i) => i * 110 });
      } catch (error) {
        clearInterval(ticker);
        mount(bot.querySelector(".bubble"), html`<div class="error-box">${error.message}</div>`);
      }
      bot.scrollIntoView({ behavior: motionEnabled() ? "smooth" : "auto", block: "end" });
    };
    ctx.ask = ask; // lets "Ask analyst" in a drawer continue this conversation (see main.js)

    $("[data-form]", view).addEventListener("submit", (e) => { e.preventDefault(); ask(input.value); });
    view.addEventListener("click", (e) => {
      const suggestion = e.target.closest("[data-q]");
      if (suggestion) ask(suggestion.dataset.q);
    });
    if (queued) { const q = queued; queued = null; ask(q); }
    else input.focus({ preventScroll: true });
  },
};

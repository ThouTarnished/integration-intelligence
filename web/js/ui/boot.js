// First-visit boot sequence (once per browser session). It reports real numbers fetched from
// the API while the logo draws itself. Any key or click skips it; reduced motion skips it entirely.
import { get } from "../core/api.js";
import { $, esc, sleep } from "../core/dom.js";
import { animate, drawIn, motionEnabled } from "../core/motion.js";

export async function boot() {
  const el = $("#boot");
  let seen = false;
  try { seen = sessionStorage.getItem("iip-booted") === "1"; sessionStorage.setItem("iip-booted", "1"); } catch { /* ignore */ }
  if (seen || !motionEnabled()) { el.remove(); return; }

  el.hidden = false;
  let skipped = false;
  const skip = () => { skipped = true; };
  addEventListener("keydown", skip, { once: true });
  el.addEventListener("click", skip, { once: true });

  const facts = Promise.all([get("/risk/rules"), get("/integration/health")]).catch(() => [null, null]);
  drawIn(el.querySelectorAll(".trace"), { duration: 900, step: 120 });
  animate(el.querySelector(".core"), { scale: [0, 1], duration: 700, delay: 600, ease: "outBack(3)" });
  animate(el.querySelector(".boot-title"), { opacity: [0, 1], x: [-8, 0], duration: 700, delay: 300, ease: "outExpo" });
  const bar = el.querySelector(".boot-bar i");

  const [rules, health] = await facts;
  const lines = [
    "Opening secure channel to NovaBank",
    rules ? `Rulebook loaded · ${rules.signals.length} signals, ${rules.levels.length} levels` : "Rulebook loaded",
    health ? `Event store online · ${health.events_received.toLocaleString()} events` : "Event store online",
    "Live stream ready",
  ];
  const host = el.querySelector(".boot-lines");
  for (const [i, text] of lines.entries()) {
    if (skipped) break;
    host.insertAdjacentHTML("beforeend", `<div><span class="ok">✓</span><span>${esc(text)}</span></div>`);
    animate(host.lastElementChild, { opacity: [0, 1], x: [-6, 0], duration: 360, ease: "outExpo" });
    animate(bar, { scaleX: (i + 1) / lines.length, duration: 380, ease: "outExpo" });
    await sleep(260);
  }
  if (!skipped) await sleep(220);
  removeEventListener("keydown", skip);
  await animate(el, { opacity: [1, 0], scale: [1, 1.015], filter: ["blur(0px)", "blur(6px)"], duration: 480, ease: "inOutQuad" });
  el.remove();
}

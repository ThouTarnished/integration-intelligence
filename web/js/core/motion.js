// The only module that talks to anime.js (vendored v4 UMD build -> window.anime).
// Rules: content is never hidden by CSS waiting for JS, so if anime.js is missing the UI still
// works; and when motion is off (OS setting or in-app toggle) every animation jumps to its end.
import { fmt } from "./dom.js";

const A = window.anime;
const reduceQuery = matchMedia("(prefers-reduced-motion: reduce)");
const STORAGE_KEY = "iip-motion";

try {
  if (localStorage.getItem(STORAGE_KEY) === "off") document.documentElement.dataset.motion = "off";
} catch { /* storage unavailable: keep defaults */ }

const hasAnime = Boolean(A);
// Hidden tabs skip motion entirely: anime.js pauses its engine while a document is hidden, which
// would otherwise leave freshly rendered content frozen at its invisible start state.
export const motionEnabled = () => hasAnime && !reduceQuery.matches && document.documentElement.dataset.motion !== "off"
  && document.visibilityState === "visible";

export function setMotion(enabled) {
  document.documentElement.dataset.motion = enabled ? "on" : "off";
  try { localStorage.setItem(STORAGE_KEY, enabled ? "on" : "off"); } catch { /* ignore */ }
}

const toArray = (targets) =>
  !targets ? [] : typeof targets === "string" ? [...document.querySelectorAll(targets)]
    : targets instanceof Element ? [targets] : [...targets];

/** Set values instantly (used to pre-hide elements a timeline will reveal). */
export const set = (targets, props) => (hasAnime ? A.utils.set(targets, props) : null);
export const motionPath = (path) => (hasAnime ? A.svg.createMotionPath(path) : {});

export const stagger = (value, options) => (hasAnime ? A.stagger(value, options) : 0);
export const spring = (bounce = 0.12, duration = 450) => (hasAnime ? A.spring({ bounce, duration }) : "linear");
const chartEase = () => (hasAnime ? A.cubicBezier(0.85, 0, 0.15, 1) : "linear");

/** anime.animate, but motion-aware. Always returns something awaitable. */
export function animate(targets, params) {
  if (!hasAnime) return Promise.resolve();
  if (!motionEnabled()) return A.animate(targets, { ...params, duration: 0, delay: 0, loop: 0, ease: "linear" });
  return A.animate(targets, params);
}

export function timeline(params = {}) {
  if (!hasAnime) return null;
  return A.createTimeline(motionEnabled() ? params : { ...params, defaults: { ...(params.defaults || {}), duration: 0, delay: 0 } });
}

/** Blur-fade-up entrance with a capped stagger (only the first `max` items animate). */
export function enter(targets, { y = 14, delay = 0, step = 45, blur = 6, duration = 640, max = 14 } = {}) {
  const els = toArray(targets).slice(0, max);
  if (!els.length || !motionEnabled()) return Promise.resolve();
  const params = {
    opacity: [0, 1], y: [y, 0], duration, ease: "outExpo",
    delay: A.stagger(step, { start: delay }),
    onComplete: () => els.forEach((el) => ["opacity", "transform", "filter"].forEach((p) => el.style.removeProperty(p))),
  };
  if (blur) params.filter = [`blur(${blur}px)`, "blur(0px)"];
  return A.animate(els, params);
}

/** Count a number up (or from its previous value) into an element. */
export function countUp(el, to, { duration = 1100, delay = 0, format = fmt.num } = {}) {
  if (!el) return;
  const from = Number(el.dataset.value ?? 0);
  el.dataset.value = to;
  el.setAttribute("aria-label", format(to));
  if (!motionEnabled() || from === to) {
    el.textContent = format(to);
    return;
  }
  const state = { v: from };
  el.textContent = format(from);
  A.animate(state, { v: to, duration, delay, ease: "outExpo", onUpdate: () => { el.textContent = format(state.v); } });
}

/** Draw SVG strokes in (line-drawing effect). */
export function drawIn(paths, { duration = 1200, delay = 0, step = 60, ease = "inOutQuad" } = {}) {
  const els = toArray(paths);
  if (!els.length || !motionEnabled()) return Promise.resolve();
  return A.animate(A.svg.createDrawable(els), { draw: ["0 0", "0 1"], duration, ease, delay: A.stagger(step, { start: delay }) });
}

/** Reveal a chart left-to-right by growing its clip rect (Bklit-style). */
export function clipReveal(rect, width, { duration = 1100, delay = 0 } = {}) {
  if (!rect) return Promise.resolve();
  if (!motionEnabled()) { rect.setAttribute("width", width); return Promise.resolve(); }
  return A.animate(rect, { width: [0, width], duration, delay, ease: chartEase() });
}

/** FLIP: animate children from their old positions after `mutate` reorders the DOM. */
export function flip(container, mutate, { duration = 420 } = {}) {
  const before = new Map([...container.children].map((child) => [child, child.getBoundingClientRect()]));
  mutate();
  if (!motionEnabled()) return;
  for (const child of container.children) {
    const prev = before.get(child);
    if (!prev) continue;
    const now = child.getBoundingClientRect();
    const dx = prev.left - now.left, dy = prev.top - now.top;
    if (dx || dy) A.animate(child, { x: [dx, 0], y: [dy, 0], ease: A.spring({ bounce: 0.08, duration }) });
  }
}

/** Keyed FLIP for re-rendered lists: elements are matched by data-<key>, so moved items glide
 *  from their old position and brand-new ones fade in, even though the DOM nodes are new. */
export function flipKeyed(root, selector, mutate, { key = "id", duration = 460 } = {}) {
  const before = new Map([...root.querySelectorAll(selector)].map((el) => [el.dataset[key], el.getBoundingClientRect()]));
  mutate();
  if (!motionEnabled()) return;
  for (const el of root.querySelectorAll(selector)) {
    const prev = before.get(el.dataset[key]);
    if (!prev) {
      A.animate(el, { opacity: [0, 1], scale: [0.96, 1], duration: 420, ease: "outExpo" });
      continue;
    }
    const now = el.getBoundingClientRect();
    const dx = prev.left - now.left, dy = prev.top - now.top;
    if (dx || dy) A.animate(el, { x: [dx, 0], y: [dy, 0], ease: A.spring({ bounce: 0.1, duration }) });
  }
}

/** Type text into an element character by character. */
export async function typeText(el, text, { speed = 14 } = {}) {
  if (!motionEnabled()) { el.textContent = text; return; }
  el.textContent = "";
  for (let i = 0; i < text.length; i += 2) {
    el.textContent = text.slice(0, i + 2);
    await new Promise((resolve) => setTimeout(resolve, speed));
  }
}

/** Slide a segmented control's pill under the pressed button. */
export function movePill(seg, instant = false) {
  const pill = seg.querySelector(".pill");
  const active = seg.querySelector('[aria-pressed="true"]');
  if (!pill || !active) return;
  const target = { x: active.offsetLeft, width: active.offsetWidth };
  if (instant || !motionEnabled()) {
    if (hasAnime) A.utils.set(pill, target);
    else Object.assign(pill.style, { width: `${target.width}px`, transform: `translateX(${target.x}px)` });
    return;
  }
  A.animate(pill, { x: target.x, width: target.width, ease: A.spring({ bounce: 0.18, duration: 380 }) });
}

/** Cursor spotlight on panel borders: every panel in the hovered grid tracks the pointer. */
export function installSpotlight() {
  let frame = 0, last = null;
  document.addEventListener("pointermove", (e) => {
    last = e;
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      const host = last.target.closest?.(".grid, .scenarios");
      if (!host) return;
      for (const panel of host.querySelectorAll(":scope > .panel, :scope > * > .panel, :scope > .scenario")) {
        const r = panel.getBoundingClientRect();
        panel.style.setProperty("--mx", `${last.clientX - r.left}px`);
        panel.style.setProperty("--my", `${last.clientY - r.top}px`);
      }
    });
  }, { passive: true });
}

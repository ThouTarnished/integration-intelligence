// Right-hand detail sheet with a small history stack (incident -> event -> back).
// The frame mounts once per opening; navigating only swaps the head and body, so the
// slide-in animation is never cut short by fast API responses.
import { $, html, mount, trapTab } from "../core/dom.js";
import { animate, enter } from "../core/motion.js";
import { skeleton } from "./components.js";
import { icon } from "./icons.js";

const root = () => $("#drawer");
const stack = []; // render functions, newest last
let lastFocus = null, cleanup = null, closing = null; // `closing` marks an exit animation in progress

const shell = () => html`<div class="drawer-backdrop" data-close></div>
  <aside class="drawer-sheet" role="dialog" aria-modal="true" tabindex="-1">
    <header class="drawer-head"></header>
    <div class="drawer-body"></div>
  </aside>`;

const head = ({ title = "", eyebrow = "", badges = "" } = {}) => html`
  ${stack.length > 1 ? html`<button class="btn sm icon ghost" data-back aria-label="Back">${icon("back", 16)}</button>` : ""}
  <div style="min-width:0">
    <div class="eyebrow">${eyebrow}</div>
    <h2>${title}</h2>
    ${badges ? html`<div class="chips" style="margin-top:8px">${badges}</div>` : ""}
  </div>
  <button class="btn sm icon ghost close" data-close aria-label="Close">${icon("x", 16)}</button>`;

/** Runs the teardown the current view returned from `after()`, such as stopping a chart's resize observer. */
function teardown() {
  cleanup?.();
  cleanup = null;
}

async function show(render) {
  const el = root();
  const body = el.querySelector(".drawer-body");
  teardown();
  mount(el.querySelector(".drawer-head"), head({ title: "Loading…" }));
  mount(body, skeleton(6));
  try {
    const view = await render();
    if (stack[stack.length - 1] !== render) return; // superseded by a newer drawer
    mount(el.querySelector(".drawer-head"), head(view));
    el.querySelector(".drawer-sheet").setAttribute("aria-label", view.title || "Details");
    mount(body, view.body);
    body.scrollTop = 0;
    enter(body.children, { y: 10, step: 55, blur: 4 });
    const done = view.after?.(body);
    if (typeof done === "function") cleanup = done;
  } catch (error) {
    if (stack[stack.length - 1] === render) mount(body, html`<div class="error-box">${error.message}</div>`);
  }
}

/** Open a drawer. `render` is async and resolves to { title, eyebrow, badges, body, after(bodyEl) }. */
export function openDrawer(render) {
  const el = root();
  if (el.hidden || closing) {
    if (el.hidden) lastFocus = document.activeElement;
    closing = null;
    stack.length = 0;
    mount(el, shell());
    el.hidden = false;
    el.querySelector(".drawer-sheet").focus({ preventScroll: true });
    animate(el.querySelector(".drawer-backdrop"), { opacity: [0, 1], duration: 260, ease: "out(2)" });
    animate(el.querySelector(".drawer-sheet"), { x: [56, 0], opacity: [0, 1], duration: 560, ease: "outExpo" });
  }
  stack.push(render);
  show(render);
}

export async function closeDrawer() {
  const el = root();
  if (el.hidden || closing) return;
  const mine = (closing = {});
  stack.length = 0;
  teardown();
  await Promise.all([
    animate(el.querySelector(".drawer-sheet"), { x: [0, 40], opacity: [1, 0], duration: 220, ease: "in(2)" }),
    animate(el.querySelector(".drawer-backdrop"), { opacity: [1, 0], duration: 220 }),
  ]);
  if (closing !== mine) return; // reopened while animating out: leave the new drawer alone
  closing = null;
  el.hidden = true;
  el.innerHTML = "";
  lastFocus?.focus?.();
}

export const drawerOpen = () => !root().hidden;

export function installDrawer() {
  root().addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) closeDrawer();
    else if (e.target.closest("[data-back]") && stack.length > 1) {
      stack.pop();
      show(stack[stack.length - 1]);
    }
  });
  root().addEventListener("keydown", (e) => trapTab(root().querySelector(".drawer-sheet"), e));
}

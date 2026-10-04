// Stacked notifications (bottom-right). Risk-level colour on the left edge.
import { $, html } from "../core/dom.js";
import { animate, spring } from "../core/motion.js";

const MAX = 4;

export function toast({ title, body = "", level = "", timeout = 5200, onClick } = {}) {
  const host = $("#toasts");
  const el = document.createElement("div");
  el.className = `toast${level ? ` lvl-${level}` : ""}`;
  el.setAttribute("role", "status");
  el.innerHTML = String(html`<div><div class="t-title">${title}</div>${body ? html`<div class="t-body">${body}</div>` : ""}</div>`);
  host.append(el);
  while (host.children.length > MAX) host.firstElementChild.remove();
  animate(el, { x: [40, 0], opacity: [0, 1], scale: [0.97, 1], ease: spring(0.2, 420) });

  let timer;
  const dismiss = async () => {
    clearTimeout(timer);
    await animate(el, { x: [0, 30], opacity: [1, 0], duration: 200, ease: "in(2)" });
    el.remove();
  };
  el.addEventListener("click", () => { onClick?.(); dismiss(); });
  el.addEventListener("mouseenter", () => clearTimeout(timer));
  el.addEventListener("mouseleave", () => { timer = setTimeout(dismiss, 2000); });
  timer = setTimeout(dismiss, timeout);
}

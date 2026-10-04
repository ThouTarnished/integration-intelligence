// One shared, pointer-following tooltip for charts and the map. Flips to stay on screen.
let el = null;

function ensure() {
  if (!el) {
    el = document.createElement("div");
    el.className = "tooltip";
    el.setAttribute("role", "tooltip");
    document.body.append(el);
    // The chart under the pointer can change without a pointerleave (a drawer closed with Escape, a scroll, a click
    // that opens something): any of those hides the tooltip, so it never lingers over content it no longer describes.
    for (const type of ["keydown", "pointerdown"]) addEventListener(type, hideTip);
    addEventListener("scroll", hideTip, { capture: true, passive: true });
  }
  return el;
}

export function showTip(clientX, clientY, content) {
  const tip = ensure();
  tip.innerHTML = String(content);
  tip.classList.add("show");
  const { width, height } = tip.getBoundingClientRect();
  const x = clientX + 16 + width > innerWidth ? clientX - width - 16 : clientX + 16;
  const y = Math.min(Math.max(8, clientY - height / 2), innerHeight - height - 8);
  tip.style.transform = `translate(${x}px, ${y}px)`;
  tip.style.left = "0";
  tip.style.top = "0";
}

export function hideTip() {
  el?.classList.remove("show");
}

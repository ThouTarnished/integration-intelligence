// Dot-matrix threat map. Land is a canvas of ~3.8k dots (decoded from a 3.6 KB bit mask);
// cities, travel arcs and live pings are an SVG overlay. Equirectangular projection.
import { esc, fmt, raw } from "../core/dom.js";
import { animate, drawIn, motionEnabled, motionPath, stagger } from "../core/motion.js";
import { WORLD } from "../data/world-dots.js";
import { hideTip, showTip } from "../ui/tooltip.js";
import { LEVEL_COLORS, cssVar } from "./core.js";

const LAND = (() => {
  const cells = [];
  WORLD.mask.forEach((hex, row) => {
    const bits = [...hex].map((h) => parseInt(h, 16).toString(2).padStart(4, "0")).join("");
    for (let col = 0; col < WORLD.cols; col++) if (bits[col] === "1") cells.push([col, row]);
  });
  return cells;
})();
const NS = "http://www.w3.org/2000/svg";
const MAX_ARCS = 36;

export function worldMap(el, geo, { onCity } = {}) {
  el.classList.add("worldmap");
  el.innerHTML = `<canvas aria-hidden="true"></canvas><svg class="map-overlay" role="img" aria-label="Map of event locations and travel"></svg>`;
  const canvas = el.querySelector("canvas"), svg = el.querySelector("svg");
  let W = 0, H = 0, cell = 0, data = geo, revealed = false;
  const colors = LEVEL_COLORS();

  const project = (lat, lon) => [((lon - WORLD.lonMin) / 360) * W, ((WORLD.latMax - lat) / (WORLD.latMax - WORLD.latMin)) * H];

  function drawDots(progress = 1) {
    const dpr = window.devicePixelRatio || 1;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const front = progress * (W + 60);
    const hot = data.cities.filter((c) => c.max_risk >= 60).map((c) => ({ p: project(c.lat, c.lon), color: colors[c.level] }));
    const reach = cell * 4.2, radius = Math.max(0.9, cell * 0.27);
    const base = new Path2D(), tinted = [];
    for (const [col, row] of LAND) {
      const x = (col + 0.5) * cell, y = (row + 0.5) * cell;
      if (x > front) continue;
      let best = null;
      for (const h of hot) {
        const d = Math.hypot(h.p[0] - x, h.p[1] - y);
        if (d < reach && (!best || d < best.d)) best = { d, color: h.color };
      }
      if (best) tinted.push([x, y, best.color, 0.75 * (1 - best.d / reach) + 0.12]);
      else { base.moveTo(x + radius, y); base.arc(x, y, radius, 0, Math.PI * 2); }
    }
    ctx.fillStyle = "rgba(255,255,255,0.15)";
    ctx.fill(base);
    for (const [x, y, color, alpha] of tinted) {
      ctx.globalAlpha = alpha;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(x, y, radius * 1.15, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    if (progress < 1) { // the scan line at the reveal front
      const grad = ctx.createLinearGradient(front - 40, 0, front, 0);
      grad.addColorStop(0, "rgba(62,230,209,0)");
      grad.addColorStop(1, "rgba(62,230,209,0.35)");
      ctx.fillStyle = grad;
      ctx.fillRect(front - 40, 0, 40, H);
    }
  }

  const arcPath = (a, b) => {
    const [x0, y0] = project(a.lat, a.lon), [x1, y1] = project(b.lat, b.lon);
    const lift = Math.min(90, Math.hypot(x1 - x0, y1 - y0) * 0.28);
    return `M${x0.toFixed(1)},${y0.toFixed(1)} Q${((x0 + x1) / 2).toFixed(1)},${(Math.min(y0, y1) - lift).toFixed(1)} ${x1.toFixed(1)},${y1.toFixed(1)}`;
  };
  const arcKind = (arc) => (arc.impossible ? "impossible" : arc.assessed === false ? "hostile" : "plausible");

  function arcNode(arc) {
    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", arcPath(arc.from, arc.to));
    path.setAttribute("class", `arc ${arcKind(arc)}`);
    path.dataset.tip = `${arc.from.name} → ${arc.to.name}|${arc.distance_km ?? "?"}|${arc.speed_kmh ?? "?"}|${arcKind(arc)}`;
    return path;
  }

  function layout(animateIn) {
    W = el.clientWidth;
    H = Math.round((W * WORLD.rows) / WORLD.cols);
    cell = W / WORLD.cols;
    el.style.height = `${H}px`;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = `${W}px`;
    canvas.style.height = `${H}px`;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

    // Arcs: unique routes, most recent first.
    const seen = new Set();
    const arcs = data.arcs.filter((a) => {
      const key = `${a.from.name}>${a.to.name}>${arcKind(a)}`;
      return !seen.has(key) && seen.add(key);
    }).slice(0, MAX_ARCS);
    // Label the busiest cities, skipping any label that would collide with one already placed.
    const placed = [];
    const top = [...data.cities].sort((a, b) => b.events - a.events).filter((c) => {
      const [x, y] = project(c.lat, c.lon);
      if (placed.length >= 6 || placed.some(([px, py]) => Math.abs(px - x) < 64 && Math.abs(py - y) < 14)) return false;
      placed.push([x, y]);
      return true;
    }).map((c) => c.name);

    svg.innerHTML = `<g class="arcs"></g><g class="comets"></g><g class="cities">${data.cities.map((c) => {
      const [x, y] = project(c.lat, c.lon);
      const r = Math.min(5.5, 2.4 + Math.log2(1 + c.events) * 0.45);
      const pulse = c.max_risk >= 60 ? `<circle class="pulse lvl-${c.level}" cx="${x}" cy="${y}" r="${r}"/>` : "";
      const label = top.includes(c.name) ? `<text x="${x + r + 5}" y="${y + 3.5}">${esc(c.name.split(",")[0])}</text>` : "";
      return `<g class="city lvl-${c.level}" data-name="${esc(c.name)}">${pulse}
        <circle class="hit" cx="${x}" cy="${y}" r="10"/><circle class="dot" cx="${x}" cy="${y}" r="${r}"/>${label}</g>`;
    }).join("")}</g><g class="pings"></g>`;
    const arcGroup = svg.querySelector(".arcs");
    arcs.slice().reverse().forEach((a) => arcGroup.append(arcNode(a)));

    if (animateIn && motionEnabled()) {
      const state = { p: 0 };
      animate(state, { p: 1, duration: 1600, ease: "inOutQuad", onUpdate: () => drawDots(state.p), onComplete: () => { revealed = true; } });
      animate(svg.querySelectorAll(".city"), { opacity: [0, 1], scale: [0.2, 1], duration: 700, ease: "outBack(2)", delay: stagger(35, { start: 500 }) });
      drawIn(arcGroup.querySelectorAll(".arc:not(.hostile)"), { duration: 1300, delay: 900, step: 45 });
      animate(arcGroup.querySelectorAll(".arc.hostile"), { opacity: [0, 1], duration: 900, delay: stagger(40, { start: 900 }) });
    } else {
      drawDots(1);
      revealed = true;
    }
    startComets();
  }

  // Comet flights loop forever, so they are kept to be cancelled: a relayout replaces the SVG (the old comets would
  // keep animating, detached) and leaving the page must stop them too.
  let comets = [];
  const stopComets = () => { comets.forEach((flight) => flight.cancel?.()); comets = []; };

  function startComets() {
    stopComets();
    const group = svg.querySelector(".comets");
    if (!motionEnabled() || !group) return;
    [...svg.querySelectorAll(".arc.impossible")].slice(-3).forEach((path, i) => {
      const comet = document.createElementNS(NS, "circle");
      comet.setAttribute("r", "2.6");
      comet.setAttribute("class", "comet");
      group.append(comet);
      comets.push(animate(comet, { ...motionPath(path), duration: 2600, delay: 1800 + i * 700, loop: true, loopDelay: 900, ease: "inOutSine" }));
    });
  }

  // Tooltips and clicks.
  svg.addEventListener("pointermove", (e) => {
    const city = e.target.closest(".city");
    const arc = e.target.closest(".arc");
    if (city) {
      const c = data.cities.find((x) => x.name === city.dataset.name);
      showTip(e.clientX, e.clientY, `<div class="tt-title">${esc(c.name)}</div>
        <div class="tt-row"><span>Events</span><b>${fmt.num(c.events)}</b></div>
        <div class="tt-row"><span>Peak risk</span><b style="color:${colors[c.level]}">${c.max_risk}</b></div>
        ${c.home_users ? `<div class="tt-row"><span>Home of</span><b>${c.home_users} customers</b></div>` : ""}`);
    } else if (arc) {
      const [route, km, kmh, kind] = arc.dataset.tip.split("|");
      const verdict = { impossible: "Impossible travel", hostile: "Not judged · flagged IP or failed sign-in", plausible: "Plausible travel" }[kind];
      showTip(e.clientX, e.clientY, `<div class="tt-title">${esc(verdict)}</div><div>${esc(route)}</div>
        <div class="tt-row"><span>Distance</span><b>${km === "?" ? "?" : `${fmt.num(+km)} km`}</b></div>
        <div class="tt-row"><span>Implied speed</span><b>${kmh === "?" ? "?" : `${fmt.num(+kmh)} km/h`}</b></div>`);
    } else hideTip();
  });
  svg.addEventListener("pointerleave", hideTip);
  svg.addEventListener("click", (e) => {
    const city = e.target.closest(".city");
    if (city && onCity) onCity(city.dataset.name);
  });

  // Lay out now (clientWidth forces layout even in a background tab), then again on resize.
  // ResizeObserver alone would wait for a rendering step, which hidden tabs never run.
  let width = 0;
  const check = () => {
    const w = Math.round(el.clientWidth);
    if (!w || w === width) return;
    const first = width === 0;
    width = w;
    layout(first);
  };
  const observer = new ResizeObserver(check);
  observer.observe(el);
  check();

  return {
    destroy: () => { observer.disconnect(); stopComets(); },
    /** Ripple at an event's city; draw its travel arc if it moved. */
    ping(event) {
      const city = data.cities.find((c) => c.name === event.location);
      if (!city || !W) return;
      const [x, y] = project(city.lat, city.lon);
      const ring = document.createElementNS(NS, "circle");
      ring.setAttribute("cx", x);
      ring.setAttribute("cy", y);
      ring.setAttribute("r", "3");
      ring.setAttribute("class", `ping lvl-${event.risk_level}`);
      svg.querySelector(".pings")?.append(ring);
      animate(ring, { r: [3, event.risk_score >= 60 ? 30 : 16], opacity: [0.9, 0], duration: 1600, ease: "outExpo" }).then?.(() => ring.remove());
      if (!motionEnabled()) ring.remove();
      const trip = event.context?.travel;
      const from = trip && data.cities.find((c) => c.name === trip.from);
      if (from && revealed) {
        const arc = { ...trip, from, to: city };
        const node = arcNode(arc);
        svg.querySelector(".arcs").append(node);
        if (node.classList.contains("hostile")) animate(node, { opacity: [0, 1], duration: 700 });
        else drawIn(node, { duration: 1100 });
        const all = svg.querySelectorAll(".arc");
        if (all.length > MAX_ARCS) all[0].remove();
      }
    },
  };
}

export const MAP_LEGEND = () => raw(`<div class="map-legend">
  <span><i class="lg-line plausible"></i>Plausible travel</span>
  <span><i class="lg-line hostile"></i>Unverified origin</span>
  <span><i class="lg-line impossible"></i>Impossible travel</span>
  <span><i class="lg-dot" style="background:${cssVar("--critical")}"></i>Risky city</span></div>`);

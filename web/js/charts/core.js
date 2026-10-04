// Shared chart helpers: ids, scales, a monotone cubic curve and resize handling.
let counter = 0;
export const uid = (prefix) => `${prefix}-${++counter}`;

/** Round an axis maximum up to a "nice" number (1, 2, 2.5, 5 x 10^n). */
export function niceMax(value) {
  if (value <= 0) return 1;
  const exp = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 2.5, 5, 10].find((s) => s * exp >= value);
  return step * exp;
}

export const linear = (d0, d1, r0, r1) => (v) => r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0);

/** Monotone cubic interpolation (Fritsch–Carlson): smooth, but never overshoots the data. */
export function monotonePath(points) {
  const n = points.length;
  if (n === 0) return "";
  if (n === 1) return `M${points[0][0]},${points[0][1]}`;
  const dx = [], slope = [], tangent = new Array(n);
  for (let i = 0; i < n - 1; i++) {
    dx[i] = points[i + 1][0] - points[i][0];
    slope[i] = (points[i + 1][1] - points[i][1]) / (dx[i] || 1);
  }
  tangent[0] = slope[0];
  tangent[n - 1] = slope[n - 2];
  for (let i = 1; i < n - 1; i++) tangent[i] = slope[i - 1] * slope[i] <= 0 ? 0 : (slope[i - 1] + slope[i]) / 2;
  for (let i = 0; i < n - 1; i++) {
    if (slope[i] === 0) { tangent[i] = tangent[i + 1] = 0; continue; }
    const a = tangent[i] / slope[i], b = tangent[i + 1] / slope[i], s = a * a + b * b;
    if (s > 9) { const k = 3 / Math.sqrt(s); tangent[i] = k * a * slope[i]; tangent[i + 1] = k * b * slope[i]; }
  }
  let d = `M${points[0][0]},${points[0][1]}`;
  for (let i = 0; i < n - 1; i++) {
    const h = dx[i] / 3;
    d += `C${points[i][0] + h},${points[i][1] + h * tangent[i]} ${points[i + 1][0] - h},${points[i + 1][1] - h * tangent[i + 1]} ${points[i + 1][0]},${points[i + 1][1]}`;
  }
  return d;
}

/** Re-run `draw(width)` whenever the element's width changes (first call animates). */
export function responsive(el, draw) {
  let width = 0, first = true;
  const run = () => {
    const w = Math.round(el.clientWidth);
    if (!w || w === width) return;
    width = w;
    draw(w, first);
    first = false;
  };
  const observer = new ResizeObserver(run);
  observer.observe(el);
  run();
  return () => observer.disconnect();
}

/** Edge-fading mask so gridlines dissolve at the left/right ends. */
export const fadeMask = (id, w, h) => `<linearGradient id="${id}-g"><stop offset="0" stop-color="#fff" stop-opacity="0"/>
  <stop offset=".08" stop-color="#fff"/><stop offset=".92" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
  <mask id="${id}"><rect width="${w}" height="${h}" fill="url(#${id}-g)"/></mask>`;

/** SVG presentation attributes don't reliably accept var(); resolve tokens to real colours. */
export const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
export const resolveColor = (color) => (color?.startsWith("--") ? cssVar(color) : color);
export const LEVEL_COLORS = () => ({
  LOW: cssVar("--low"), MEDIUM: cssVar("--medium"), HIGH: cssVar("--high"), CRITICAL: cssVar("--critical"),
});

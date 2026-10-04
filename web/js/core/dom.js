// DOM helpers and formatters. `html` is a tagged template that escapes every
// interpolated value unless it is itself `html`/`raw` output, so XSS-safety is the default.

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ESCAPES[c]);

class SafeHTML {
  constructor(value) { this.value = value; }
  toString() { return this.value; }
}
export const raw = (value) => new SafeHTML(String(value));

const render = (value) => {
  if (value == null || value === false) return "";
  if (Array.isArray(value)) return value.map(render).join("");
  if (value instanceof SafeHTML) return value.value;
  return esc(value);
};

export function html(strings, ...values) {
  let out = strings[0];
  values.forEach((value, i) => { out += render(value) + strings[i + 1]; });
  return new SafeHTML(out);
}

/** Replace an element's content and return the element. */
export function mount(el, content) {
  el.innerHTML = String(content);
  return el;
}

// ---------- formatting ----------
const NUMBER = new Intl.NumberFormat("en-US");
const MONEY = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
export const utc = (iso) => (iso ? new Date(/Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`) : null);

export const fmt = {
  num: (n) => NUMBER.format(Math.round(n ?? 0)),
  count: (n, noun) => `${NUMBER.format(n ?? 0)} ${noun}${n === 1 ? "" : "s"}`,
  money: (n) => MONEY.format(n ?? 0),
  pct: (n, digits = 0) => `${(n * 100).toFixed(digits)}%`,
  time: (iso) => utc(iso)?.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }) ?? "—",
  dateTime: (iso) => utc(iso)?.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }) ?? "—",
  ago(iso) {
    const date = utc(iso);
    if (!date) return "—";
    const s = Math.max(0, (Date.now() - date) / 1000);
    if (s < 45) return "just now";
    if (s < 3600) return `${Math.round(s / 60)}m ago`;
    if (s < 86400) return `${Math.round(s / 3600)}h ago`;
    return `${Math.round(s / 86400)}d ago`;
  },
  duration(seconds) {
    const d = Math.floor(seconds / 86400), h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60), s = Math.floor(seconds % 60);
    return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : m ? `${m}m ${s}s` : `${s}s`;
  },
  initials: (name) => (name || "?").split(/\s+/).map((p) => p[0]).join("").slice(0, 2).toUpperCase(),
  type: (t) => ({ login: "Login", transaction: "Transaction", resource_access: "Resource access", password_reset: "Password reset" }[t] || t),
};

export const LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
export const levelOf = (score) => (score >= 80 ? "CRITICAL" : score >= 60 ? "HIGH" : score >= 30 ? "MEDIUM" : "LOW");
export const debounce = (fn, ms) => {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
};
export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Keeps Tab and Shift+Tab inside a modal (the drawer, the palette): focus wraps from the last control to the first. */
export function trapTab(container, e) {
  if (e.key !== "Tab" || !container) return;
  const items = [...container.querySelectorAll("a[href], button:not([disabled]), input, select, textarea, [tabindex='0']")]
    .filter((el) => el.offsetParent !== null);
  if (!items.length) return;
  const first = items[0], last = items[items.length - 1], inside = items.includes(document.activeElement);
  if (e.shiftKey && (!inside || document.activeElement === first)) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && (!inside || document.activeElement === last)) { e.preventDefault(); first.focus(); }
}

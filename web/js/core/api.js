// Thin fetch wrapper for /api/v1. Write requests carry the X-API-Key header.
// In demo mode the server injects the key into <meta name="iip-api-key">; otherwise the
// user is asked for it once per browser session.
import { bus } from "./bus.js";

const BASE = "/api/v1";
const injected = document.querySelector('meta[name="iip-api-key"]')?.content || "";
let apiKey = injected && injected !== "__IIP_API_KEY__" ? injected : sessionStorage.getItem("iip-api-key") || "";

export function setKey(key) {
  apiKey = key.trim();
  sessionStorage.setItem("iip-api-key", apiKey);
}

class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

/** Low-level call that also reports status, latency and request id (used by the API console). */
export async function request(path, { method = "GET", body, signal } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && apiKey) headers["X-API-Key"] = apiKey;
  const started = performance.now();
  const response = await fetch(BASE + path, {
    method, headers, signal, body: body === undefined ? undefined : typeof body === "string" ? body : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  return {
    ok: response.ok, status: response.status, data,
    ms: performance.now() - started,
    requestId: response.headers.get("X-Request-ID"),
    serverTime: response.headers.get("X-Response-Time"),
  };
}

async function api(path, options = {}) {
  const result = await request(path, options);
  if (result.status === 401 && options.method && options.method !== "GET") bus.emit("auth:required");
  if (!result.ok) {
    const detail = result.data?.detail;
    const message = typeof detail === "string" ? detail
      : Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : `HTTP ${result.status}`;
    throw new ApiError(message, result.status);
  }
  return result.data;
}

export const get = (path, options) => api(path, options);
export const post = (path, body) => api(path, { method: "POST", body: body ?? {} });
export const patch = (path, body) => api(path, { method: "PATCH", body });

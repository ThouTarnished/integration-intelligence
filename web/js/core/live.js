// Server-Sent Events client. EventSource retries a dropped connection by itself (the server sends `retry: 3000`),
// but gives up for good when a retry gets an error response, such as a proxy's 502 while the server restarts; that
// case reconnects here, with a growing delay. After any reconnect, `live:resync` tells pages to refetch, because
// messages sent while the connection was down are lost.
import { bus } from "./bus.js";

export const live = { state: "connecting" };
let opened = false, retryDelay = 2000;

/** The connection dot (the rail's and the overview's): a pulse when live, yellow while reconnecting, grey offline. */
export const liveDotClass = (state) => `live-dot${state === "live" ? "" : state === "connecting" ? " warn" : " off"}`;

function setState(state) {
  if (live.state === state) return;
  live.state = state;
  bus.emit("live:state", state);
}

export function connectLive() {
  const source = new EventSource("/api/v1/stream");
  source.onopen = () => {
    if (opened) bus.emit("live:resync");
    opened = true;
    retryDelay = 2000;
    setState("live");
  };
  source.onerror = () => {
    if (source.readyState !== EventSource.CLOSED) return setState("connecting");
    setState("offline");
    setTimeout(connectLive, retryDelay); // the browser gave up: try again, waiting longer each time, up to 30 s
    retryDelay = Math.min(retryDelay * 2, 30000);
  };
  for (const type of ["event", "incident", "traffic", "reset"]) {
    source.addEventListener(type, (message) => {
      try {
        bus.emit(`live:${type}`, JSON.parse(message.data));
      } catch (error) {
        console.warn("Malformed live message", error);
      }
    });
  }
}

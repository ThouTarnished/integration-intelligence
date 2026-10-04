// App-wide pub/sub. Pages subscribe to live events here instead of to the EventSource directly.
const target = new EventTarget();

export const bus = {
  on(type, handler) {
    const listener = (e) => handler(e.detail);
    target.addEventListener(type, listener);
    return () => target.removeEventListener(type, listener);
  },
  emit(type, detail) {
    target.dispatchEvent(new CustomEvent(type, { detail }));
  },
};

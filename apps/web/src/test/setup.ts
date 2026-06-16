import "@testing-library/jest-dom/vitest";

/** Minimal sessionStorage for unit tests (jsdom does not provide it by default). */
const sessionStore = new Map<string, string>();

Object.defineProperty(globalThis, "sessionStorage", {
  value: {
    get length() {
      return sessionStore.size;
    },
    clear() {
      sessionStore.clear();
    },
    getItem(key: string) {
      return sessionStore.get(key) ?? null;
    },
    key(index: number) {
      return [...sessionStore.keys()][index] ?? null;
    },
    removeItem(key: string) {
      sessionStore.delete(key);
    },
    setItem(key: string, value: string) {
      sessionStore.set(key, value);
    },
  },
  configurable: true,
});

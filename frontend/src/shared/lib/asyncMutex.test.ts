import { describe, expect, it } from "vitest";

import { runExclusive } from "./asyncMutex";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

// Flush enough microtasks for a runExclusive callback (queued behind
// prev.catch().then()) to actually start.
const flush = () => new Promise((r) => setTimeout(r, 0));

describe("runExclusive", () => {
  it("serializes calls sharing a key (no overlap)", async () => {
    const events: string[] = [];
    const first = deferred<void>();

    const a = runExclusive("serialize", async () => {
      events.push("a:start");
      await first.promise;
      events.push("a:end");
    });
    const b = runExclusive("serialize", async () => {
      events.push("b:start");
    });

    await flush();
    // a has started; b must still be queued behind it.
    expect(events).toEqual(["a:start"]);

    first.resolve();
    await Promise.all([a, b]);
    expect(events).toEqual(["a:start", "a:end", "b:start"]);
  });
  it("runs different keys concurrently", async () => {
    const events: string[] = [];
    const gate = deferred<void>();

    const a = runExclusive("key-a", async () => {
      events.push("a:start");
      await gate.promise;
    });
    const b = runExclusive("key-b", async () => {
      events.push("b:start");
    });

    await b;
    // b (different key) started without waiting for a.
    expect(events).toContain("b:start");
    gate.resolve();
    await a;
  });

  it("a rejection does not break the chain for later callers", async () => {
    const boom = runExclusive("reject-chain", async () => {
      throw new Error("boom");
    });
    await expect(boom).rejects.toThrow("boom");

    const ok = runExclusive("reject-chain", async () => "ok");
    await expect(ok).resolves.toBe("ok");
  });

  it("returns each call's own result", async () => {
    const [a, b] = await Promise.all([
      runExclusive("own-result", async () => 1),
      runExclusive("own-result", async () => 2),
    ]);
    expect([a, b]).toEqual([1, 2]);
  });
});

import { describe, expect, it, vi } from "vitest";

import { enqueueSerialPostPatch } from "./enqueueSerialPostPatch";

describe("enqueueSerialPostPatch", () => {
  it("runs tasks for the same post sequentially", async () => {
    const order: number[] = [];

    await enqueueSerialPostPatch("post-1", async () => {
      order.push(1);
    });
    await enqueueSerialPostPatch("post-1", async () => {
      order.push(2);
    });
    await enqueueSerialPostPatch("post-1", async () => {
      order.push(3);
    });

    expect(order).toEqual([1, 2, 3]);
  });

  it("serializes concurrent enqueues for one post", async () => {
    const order: number[] = [];
    let active = 0;
    let maxActive = 0;

    const task = async (n: number) => {
      active += 1;
      maxActive = Math.max(maxActive, active);
      order.push(n);
      await new Promise((resolve) => setTimeout(resolve, 5));
      active -= 1;
    };

    await Promise.all([
      enqueueSerialPostPatch("post-1", () => task(1)),
      enqueueSerialPostPatch("post-1", () => task(2)),
      enqueueSerialPostPatch("post-1", () => task(3)),
    ]);

    expect(order).toEqual([1, 2, 3]);
    expect(maxActive).toBe(1);
  });

  it("does not block different posts", async () => {
    const fnA = vi.fn(async () => undefined);
    const fnB = vi.fn(async () => undefined);
    await Promise.all([
      enqueueSerialPostPatch("a", fnA),
      enqueueSerialPostPatch("b", fnB),
    ]);
    expect(fnA).toHaveBeenCalledOnce();
    expect(fnB).toHaveBeenCalledOnce();
  });
});

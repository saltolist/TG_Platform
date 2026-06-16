import { beforeEach, describe, expect, it, vi } from "vitest";

import { PRESENTATION_ACCOUNT_ID } from "@/shared/lib/auth/constants";
import { mergeEntityList } from "@/shared/lib/overlay/mergeEntities";
import { createEmptyOverlay } from "@/shared/lib/overlay/overlayTypes";
import {
  clearOverlay,
  mutateOverlay,
  readOverlay,
  writeOverlay,
} from "@/shared/lib/overlay/overlayStorage";

function createStorageMock(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (index) => [...data.keys()][index] ?? null,
    removeItem: (key) => {
      data.delete(key);
    },
    setItem: (key, value) => {
      data.set(key, value);
    },
  };
}

beforeEach(() => {
  vi.stubGlobal("window", { localStorage: createStorageMock() });
});

describe("overlayStorage", () => {
  it("persists overlay per account key", () => {
    mutateOverlay(
      (overlay) => {
        overlay.posts.upserts["p1"] = {
          id: "p1",
          status: "draft",
          rubric: null,
          text: "Local edit",
          notes: [],
          chats: [],
        };
      },
      PRESENTATION_ACCOUNT_ID,
    );

    const reloaded = readOverlay(PRESENTATION_ACCOUNT_ID);
    expect(reloaded.posts.upserts.p1?.text).toBe("Local edit");
  });

  it("clearOverlay resets to empty seed view on read", () => {
    writeOverlay(
      {
        ...createEmptyOverlay(),
        posts: {
          upserts: {
            p1: {
              id: "p1",
              status: "draft",
              rubric: null,
              text: "Gone",
              notes: [],
              chats: [],
            },
          },
          removedIds: [],
        },
      },
      PRESENTATION_ACCOUNT_ID,
    );
    clearOverlay(PRESENTATION_ACCOUNT_ID);
    expect(readOverlay(PRESENTATION_ACCOUNT_ID).posts.upserts).toEqual({});
  });

  it("merge hides removed seed entities", () => {
    const base = [{ id: "1", title: "Seed chat", preview: "", date: "", history: [] }];
    const merged = mergeEntityList(base, {
      upserts: {},
      removedIds: ["1"],
    });
    expect(merged).toEqual([]);
  });
});

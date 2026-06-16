import { beforeEach, describe, expect, it, vi } from "vitest";

import { useComposerTargetStore } from "@/app/model/store/composer-target-store";
import {
  composerTargetStorageKey,
  readStoredComposerTarget,
  writeStoredComposerTarget,
} from "@/shared/lib/composerTargetStorage";

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

describe("composer target store", () => {
  beforeEach(() => {
    vi.stubGlobal("window", { localStorage: createStorageMock() });
    useComposerTargetStore.setState({
      targets: {
        home: { llmId: "", webId: "" },
        gchat: { llmId: "", webId: "" },
        post: { llmId: "", webId: "" },
      },
    });
  });

  it("syncs selected LLM across all composer scopes", () => {
    useComposerTargetStore.getState().setLlmId("gchat", "llm-2");

    const { targets } = useComposerTargetStore.getState();
    expect(targets.home.llmId).toBe("llm-2");
    expect(targets.gchat.llmId).toBe("llm-2");
    expect(targets.post.llmId).toBe("llm-2");
  });

  it("persists selection per account in localStorage", () => {
    writeStoredComposerTarget("demo-full", { llmId: "llm-1", webId: "web-1" });

    useComposerTargetStore.getState().hydrateForAccount("demo-full");

    expect(useComposerTargetStore.getState().getTarget("home")).toEqual({
      llmId: "llm-1",
      webId: "web-1",
    });
    expect(readStoredComposerTarget("demo-full")).toEqual({
      llmId: "llm-1",
      webId: "web-1",
    });
    expect(window.localStorage.getItem(composerTargetStorageKey("demo-full"))).toContain("llm-1");
  });

  it("stores separate selections for different accounts", () => {
    writeStoredComposerTarget("presentation", { llmId: "llm-presentation", webId: "" });
    writeStoredComposerTarget("demo-full", { llmId: "llm-demo", webId: "" });

    useComposerTargetStore.getState().hydrateForAccount("presentation");
    expect(useComposerTargetStore.getState().getTarget("gchat").llmId).toBe("llm-presentation");

    useComposerTargetStore.getState().hydrateForAccount("demo-full");
    expect(useComposerTargetStore.getState().getTarget("gchat").llmId).toBe("llm-demo");
  });
});

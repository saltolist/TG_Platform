import { beforeEach, describe, expect, it } from "vitest";

import { usePostNavigationStore } from "./post-navigation-store";

describe("post-navigation-store", () => {
  beforeEach(() => {
    usePostNavigationStore.setState({ stacks: {}, modes: {}, chatIds: {} });
  });

  it("getMode defaults to chat", () => {
    expect(usePostNavigationStore.getState().getMode("1")).toBe("chat");
  });

  it("setMode toggles notes back to chat when notes is already active", () => {
    const { setMode, getMode } = usePostNavigationStore.getState();
    setMode("1", "notes");
    expect(getMode("1")).toBe("notes");
    setMode("1", "notes");
    expect(getMode("1")).toBe("chat");
  });

  it("pushMode saves stack and popMode restores", () => {
    const store = usePostNavigationStore.getState();
    store.setMode("1", "notes");
    store.pushMode("1", "comments");
    expect(store.getMode("1")).toBe("comments");
    expect(store.getStack("1")).toHaveLength(1);
    expect(store.getStack("1")[0]?.mode).toBe("notes");

    store.popMode("1");
    expect(store.getMode("1")).toBe("notes");
    expect(store.getStack("1")).toHaveLength(0);
  });

  it("tracks chat id in chat mode", () => {
    const store = usePostNavigationStore.getState();
    store.setMode("1", "chat", "42");
    expect(store.getCurrentPostChatId("1")).toBe("42");
    store.setMode("1", "notes");
    expect(store.getCurrentPostChatId("1")).toBeNull();
  });
});

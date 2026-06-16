import { describe, expect, it } from "vitest";
import {
  appendToActiveHistory,
  applyUserMessageSave,
  clampActiveBranchIndex,
  displayUserText,
  flattenVisibleWithPaths,
  normalizeBranchedHistory,
  resolveMessage,
  setActiveUserBranch,
  STUB_REPLY_AFTER_USER_EDIT,
} from "./chatPaths";
import type { ChatMessage } from "@/shared/types";

describe("chatPaths", () => {
  const branched: ChatMessage = {
    role: "user",
    userBranches: [
      { text: "first", continuation: [] },
      { text: "second", continuation: [] },
    ],
    activeUserBranch: 1,
  };

  it("clampActiveBranchIndex", () => {
    expect(clampActiveBranchIndex(branched)).toBe(1);
    expect(clampActiveBranchIndex({ role: "user", text: "plain" })).toBe(0);
  });

  it("displayUserText uses active branch", () => {
    expect(displayUserText(branched)).toBe("second");
    expect(displayUserText({ role: "user", text: "plain" })).toBe("plain");
    expect(displayUserText({ role: "ai", text: "x" })).toBe("");
  });

  it("resolveMessage at root", () => {
    const history: ChatMessage[] = [{ role: "user", text: "hi" }];
    expect(resolveMessage(history, [0])?.text).toBe("hi");
    expect(resolveMessage(history, [1])).toBeNull();
  });

  it("forks branch when editing message with tail", () => {
    const history: ChatMessage[] = [
      { role: "user", text: "hello" },
      { role: "ai", text: "reply" },
    ];
    const next = applyUserMessageSave(history, [0], "hello v2");
    expect(next).toHaveLength(1);
    const user = next[0];
    expect(user?.role).toBe("user");
    if (user?.role !== "user") return;
    expect(user.userBranches).toHaveLength(2);
    expect(user.activeUserBranch).toBe(1);
    expect(displayUserText(user)).toBe("hello v2");
    expect(user.userBranches?.[0]?.continuation[0]?.text).toBe("reply");
  });

  it("setActiveUserBranch switches visible branch", () => {
    const history: ChatMessage[] = [branched];
    const next = setActiveUserBranch(history, [0], 0);
    const user = next[0];
    if (user?.role !== "user") throw new Error("expected user");
    expect(user.activeUserBranch).toBe(0);
    expect(displayUserText(user)).toBe("first");
  });

  it("setActiveUserBranch changes visible continuation after fork", () => {
    const history: ChatMessage[] = [
      { role: "user", text: "hello" },
      { role: "ai", text: "original reply" },
    ];
    const afterEdit = applyUserMessageSave(history, [0], "hello v2");
    const branch1 = flattenVisibleWithPaths(afterEdit).map(({ message }) =>
      message.role === "user" ? displayUserText(message) : message.text,
    );
    expect(branch1[0]).toBe("hello v2");
    expect(branch1[1]).toBe(STUB_REPLY_AFTER_USER_EDIT.text);

    const branch0 = flattenVisibleWithPaths(setActiveUserBranch(afterEdit, [0], 0)).map(
      ({ message }) => (message.role === "user" ? displayUserText(message) : message.text),
    );
    expect(branch0[0]).toBe("hello");
    expect(branch0[1]).toBe("original reply");
    expect(branch0).not.toEqual(branch1);
  });

  it("normalizeBranchedHistory absorbs orphan linear tail into branch 0", () => {
    const malformed: ChatMessage[] = [
      {
        role: "user",
        userBranches: [
          { text: "hello", continuation: [] },
          { text: "hello v2", continuation: [{ role: "ai", text: "stub" }] },
        ],
        activeUserBranch: 1,
      },
      { role: "ai", text: "orphan reply" },
    ];
    const healed = normalizeBranchedHistory(malformed);
    expect(healed).toHaveLength(1);
    const user = healed[0];
    if (user?.role !== "user") throw new Error("expected user");
    expect(user.userBranches?.[0]?.continuation[0]?.text).toBe("orphan reply");

    const branch0 = flattenVisibleWithPaths(setActiveUserBranch(healed, [0], 0)).map(
      ({ message }) => (message.role === "user" ? displayUserText(message) : message.text),
    );
    const branch1 = flattenVisibleWithPaths(setActiveUserBranch(healed, [0], 1)).map(
      ({ message }) => (message.role === "user" ? displayUserText(message) : message.text),
    );
    expect(branch0).toEqual(["hello", "orphan reply"]);
    expect(branch1).toEqual(["hello v2", "stub"]);
  });

  it("appendToActiveHistory appends to active branch continuation", () => {
    const history: ChatMessage[] = [
      {
        role: "user",
        userBranches: [
          { text: "v1", continuation: [{ role: "ai", text: "branch 0 ai" }] },
          { text: "v2", continuation: [{ role: "ai", text: "branch 1 ai" }] },
        ],
        activeUserBranch: 0,
      },
    ];
    const next = appendToActiveHistory(history, { role: "user", text: "follow up" });
    const user = next[0];
    if (user?.role !== "user") throw new Error("expected user");
    expect(user.userBranches?.[0]?.continuation).toHaveLength(2);
    expect(user.userBranches?.[0]?.continuation[1]?.text).toBe("follow up");
    expect(user.userBranches?.[1]?.continuation).toHaveLength(1);
  });
});

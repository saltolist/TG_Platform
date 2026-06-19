import { describe, expect, it } from "vitest";

import {
  applyUserMessageSave,
  removeAssistantTurnAtPath,
  removeMessageAtPath,
  setActiveUserBranch,
} from "@/shared/lib/chatPaths";
import type { ChatMessage } from "@/shared/types";

describe("removeAssistantTurnAtPath", () => {
  it("removes assistant reply and the user message above it", () => {
    const history: ChatMessage[] = [
      { role: "user", text: "Вопрос 1" },
      { role: "ai", text: "Ответ 1" },
      { role: "user", text: "Вопрос 2" },
      { role: "ai", text: "Ответ 2" },
    ];

    const next = removeAssistantTurnAtPath(history, [3]);
    expect(next).toEqual([
      { role: "user", text: "Вопрос 1" },
      { role: "ai", text: "Ответ 1" },
    ]);
  });

  it("falls back to single delete when there is no user message above", () => {
    const history: ChatMessage[] = [{ role: "ai", text: "Ответ" }];
    const next = removeAssistantTurnAtPath(history, [0]);
    expect(next).toEqual([]);
    expect(removeMessageAtPath(history, [0])).toEqual([]);
  });
});

describe("applyUserMessageSave", () => {
  it("appends a new branch at the end when editing an earlier branch", () => {
    const history: ChatMessage[] = [
      { role: "user", text: "a" },
      { role: "ai", text: "reply a" },
      {
        role: "user",
        activeUserBranch: 1,
        userBranches: [
          { text: "b1", continuation: [{ role: "ai", text: "reply b1" }] },
          { text: "b2", continuation: [{ role: "ai", text: "reply b2" }] },
        ],
      },
    ];

    const switched = setActiveUserBranch(history, [2], 0);
    const next = applyUserMessageSave(switched, [2], "b1 edited");

    const fork = next[2]!;
    expect(fork.userBranches?.map((b) => b.text)).toEqual(["b1", "b2", "b1 edited"]);
    expect(fork.activeUserBranch).toBe(2);
  });

  it("still appends when editing the last branch with a tail", () => {
    const history: ChatMessage[] = [
      {
        role: "user",
        activeUserBranch: 1,
        userBranches: [
          { text: "v1", continuation: [] },
          { text: "v2", continuation: [{ role: "ai", text: "ai v2" }] },
        ],
      },
    ];

    const next = applyUserMessageSave(history, [0], "v2 edited");
    const fork = next[0]!;
    expect(fork.userBranches?.map((b) => b.text)).toEqual(["v1", "v2", "v2 edited"]);
    expect(fork.activeUserBranch).toBe(2);
  });
});

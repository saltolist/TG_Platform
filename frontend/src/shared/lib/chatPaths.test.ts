import { describe, expect, it } from "vitest";

import { removeAssistantTurnAtPath, removeMessageAtPath } from "@/shared/lib/chatPaths";
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

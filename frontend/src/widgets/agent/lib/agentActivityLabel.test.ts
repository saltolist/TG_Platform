import { describe, expect, it } from "vitest";

import type { AgentSsePayload } from "@/shared/api/schemas/agentRun";

import { selectCurrentToolLabel } from "./agentActivityLabel";

function plannerStepEvent(tool: string): AgentSsePayload {
  return { agent: { sequence: 1, type: "planner_step", payload: { tool } } };
}

function toolResultEvent(tool: string): AgentSsePayload {
  return { agent: { sequence: 2, type: "tool_result", payload: { tool } } };
}

function workspaceStepEvent(tool: string): AgentSsePayload {
  return { agent: { sequence: 1, type: "workspace_step", payload: { tool } } };
}

describe("selectCurrentToolLabel", () => {
  it("returns the default label when there are no relevant events", () => {
    expect(selectCurrentToolLabel([])).toBe("Работаю над ответом…");
  });

  it("maps the latest planner_step tool to a human phrase", () => {
    const events = [plannerStepEvent("SearchNodes"), plannerStepEvent("OpenPost")];
    expect(selectCurrentToolLabel(events)).toBe("Изучаю пост…");
  });

  it("prefers the most recent event across planner_step and tool_result", () => {
    const events = [plannerStepEvent("OpenPost"), toolResultEvent("GetPostAnalytics")];
    expect(selectCurrentToolLabel(events)).toBe("Проверяю аналитику…");
  });

  it("maps the workspace classifier decision to a human phrase", () => {
    expect(selectCurrentToolLabel([workspaceStepEvent("post_proposal")])).toBe(
      "Готовлю правку поста…",
    );
    expect(selectCurrentToolLabel([workspaceStepEvent("finish")])).toBe("Формулирую ответ…");
  });

  it("lets a later research step override the earlier workspace decision", () => {
    const events = [workspaceStepEvent("read"), plannerStepEvent("SearchNodes")];
    expect(selectCurrentToolLabel(events)).toBe("Ищу по заметкам…");
  });

  it("ignores unrelated event types and falls back for unknown tools", () => {
    const events: AgentSsePayload[] = [
      { agent: { sequence: 1, type: "graph_started", payload: {} } },
      plannerStepEvent("SomeUnknownTool"),
    ];
    expect(selectCurrentToolLabel(events)).toBe("Работаю над ответом…");
  });
});

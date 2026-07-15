import { describe, expect, it } from "vitest";

import type { AgentSsePayload } from "@/shared/api/schemas/agentRun";

import { selectCurrentToolLabel } from "./AgentActivityIndicator";

function plannerStepEvent(tool: string): AgentSsePayload {
  return { agent: { sequence: 1, type: "planner_step", payload: { tool } } };
}

function toolResultEvent(tool: string): AgentSsePayload {
  return { agent: { sequence: 2, type: "tool_result", payload: { tool } } };
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

  it("ignores unrelated event types and falls back for unknown tools", () => {
    const events: AgentSsePayload[] = [
      { agent: { sequence: 1, type: "graph_started", payload: {} } },
      plannerStepEvent("SomeUnknownTool"),
    ];
    expect(selectCurrentToolLabel(events)).toBe("Работаю над ответом…");
  });
});

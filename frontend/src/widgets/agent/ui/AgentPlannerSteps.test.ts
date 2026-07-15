import { describe, expect, it } from "vitest";

import type { AgentSsePayload } from "@/shared/api/schemas/agentRun";

import { selectPlannerSteps } from "./AgentPlannerSteps";

function plannerStepEvent(payload: Record<string, unknown>): AgentSsePayload {
  return { agent: { sequence: 1, type: "planner_step", payload } };
}

describe("selectPlannerSteps", () => {
  it("extracts planner_step events in order, ignoring other event types", () => {
    const events: AgentSsePayload[] = [
      { agent: { sequence: 1, type: "graph_started", payload: {} } },
      plannerStepEvent({
        step: 1,
        observations: [],
        reasoning: "старт",
        gap: "нет данных",
        tool: "SearchNodes",
        args: { query: "охват" },
      }),
      { agent: { sequence: 2, type: "graph_state", payload: { status: "running" } } },
      plannerStepEvent({
        step: 2,
        observations: ["найден пост 3"],
        reasoning: "нужен текст",
        gap: "note content missing",
        tool: "OpenNote",
        args: { note_id: "n1" },
      }),
    ];

    const steps = selectPlannerSteps(events);
    expect(steps).toHaveLength(2);
    expect(steps[0].tool).toBe("SearchNodes");
    expect(steps[1].tool).toBe("OpenNote");
    expect(steps[1].observations).toEqual(["найден пост 3"]);
  });

  it("drops malformed planner_step payloads instead of throwing", () => {
    const events: AgentSsePayload[] = [plannerStepEvent({ tool: "OpenNote" })];
    expect(selectPlannerSteps(events)).toEqual([]);
  });

  it("returns an empty list when there are no planner_step events", () => {
    const events: AgentSsePayload[] = [
      { agent: { sequence: 1, type: "answer", payload: { text: "ok" } } },
    ];
    expect(selectPlannerSteps(events)).toEqual([]);
  });
});

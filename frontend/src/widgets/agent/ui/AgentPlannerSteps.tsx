"use client";

import type { AgentSsePayload, PlannerStep } from "@/shared/api/schemas/agentRun";
import { plannerStepSchema } from "@/shared/api/schemas/agentRun";

type AgentPlannerStepsProps = {
  events: AgentSsePayload[];
};

export function selectPlannerSteps(events: AgentSsePayload[]): PlannerStep[] {
  return events
    .filter((event) => event.agent?.type === "planner_step")
    .map((event) => plannerStepSchema.safeParse(event.agent?.payload))
    .filter((parsed) => parsed.success)
    .map((parsed) => parsed.data);
}

// agent-runtime-sprints §3.3 exit criterion: steps 1..N with thought+tool,
// matching the run's transcript, visible in the UI.
export function AgentPlannerSteps({ events }: AgentPlannerStepsProps) {
  const steps = selectPlannerSteps(events);

  if (!steps.length) return null;

  return (
    <ol className="agent-planner-steps" data-testid="agent-planner-steps">
      {steps.map((step) => (
        <li key={step.step} className="agent-planner-steps__item">
          <div className="agent-planner-steps__reasoning">{step.reasoning}</div>
          {step.gap ? <div className="agent-planner-steps__gap">{step.gap}</div> : null}
          <div className="agent-planner-steps__tool">{step.tool}</div>
        </li>
      ))}
    </ol>
  );
}

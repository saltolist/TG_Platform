"use client";

import type { AgentRun, AgentSsePayload } from "@/shared/api/schemas/agentRun";

type AgentActivityIndicatorProps = {
  run: AgentRun | null;
  events: AgentSsePayload[];
};

const TOOL_LABELS: Record<string, string> = {
  SearchNodes: "Ищу по заметкам…",
  OpenPost: "Изучаю пост…",
  OpenNote: "Изучаю заметку…",
  ListPosts: "Просматриваю посты…",
  ListPostNotes: "Просматриваю заметки поста…",
  ListNoteAttachments: "Просматриваю вложения…",
  HydrateAttachment: "Разбираю вложение…",
  GetPostAnalytics: "Проверяю аналитику…",
  FinishRetrieval: "Собираю ответ…",
  read: "Ищу по workspace…",
  post_proposal: "Готовлю правку поста…",
  media_proposal: "Готовлю медиа…",
};

const DEFAULT_LABEL = "Работаю над ответом…";

// Last planner_step/tool_result/workspace_agent decision in the event log —
// used to pick a short human-readable phrase instead of showing the raw
// planner reasoning (which used to leak into the UI via AgentPlannerSteps).
export function selectCurrentToolLabel(events: AgentSsePayload[]): string {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const agent = events[i]?.agent;
    if (!agent) continue;
    if (agent.type === "planner_step" || agent.type === "tool_result") {
      const tool = agent.payload?.tool;
      if (typeof tool === "string" && TOOL_LABELS[tool]) return TOOL_LABELS[tool];
    }
  }
  return DEFAULT_LABEL;
}

export function AgentActivityIndicator({ run, events }: AgentActivityIndicatorProps) {
  if (!run || run.status !== "running") return null;

  const label = selectCurrentToolLabel(events);

  return (
    <div className="agent-activity-indicator" role="status" aria-live="polite">
      <span className="agent-activity-indicator__label">{label}</span>
      <span className="ai-typing-indicator" aria-hidden="true">
        <span className="ai-typing-dot" />
        <span className="ai-typing-dot" />
        <span className="ai-typing-dot" />
      </span>
    </div>
  );
}

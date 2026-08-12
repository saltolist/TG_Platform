import type { AgentSsePayload } from "@/shared/api/schemas/agentRun";

// Maps a tool/decision name from the run's event stream to a short, human
// phrase for the activity indicator. Covers both the research loop's tools
// (PascalCase: SearchNodes/OpenPost/…) and the workspace classifier's decision
// (snake_case: read/finish/post_proposal/media_proposal) so every turn — not
// just the `read` branch — has something real to show instead of the default.
const TOOL_LABELS: Record<string, string> = {
  // Workspace classifier decisions (workspace_step events).
  read: "Ищу по workspace…",
  finish: "Формулирую ответ…",
  post_proposal: "Готовлю правку поста…",
  media_proposal: "Готовлю медиа…",
  // Research loop tools (planner_step / tool_result events).
  SearchNodes: "Ищу по заметкам…",
  OpenPost: "Изучаю пост…",
  OpenNote: "Изучаю заметку…",
  ListPosts: "Просматриваю посты…",
  ListPostNotes: "Просматриваю заметки поста…",
  ListNoteAttachments: "Просматриваю вложения…",
  HydrateAttachment: "Разбираю вложение…",
  GetPostAnalytics: "Проверяю аналитику…",
  FinishRetrieval: "Собираю ответ…",
};

export const DEFAULT_AGENT_ACTIVITY_LABEL = "Работаю над ответом…";

// Picks a phrase from the latest workspace_step/planner_step/tool_result event
// in the log — used instead of leaking raw planner reasoning into the UI.
export function selectCurrentToolLabel(events: AgentSsePayload[]): string {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const agent = events[i]?.agent;
    if (!agent) continue;
    if (
      agent.type === "workspace_step" ||
      agent.type === "planner_step" ||
      agent.type === "tool_result"
    ) {
      const tool = agent.payload?.tool;
      if (typeof tool === "string" && TOOL_LABELS[tool]) return TOOL_LABELS[tool];
    }
  }
  return DEFAULT_AGENT_ACTIVITY_LABEL;
}

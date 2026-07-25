import { apiRequest, apiSseSubscribe } from "@/shared/api/httpClient";
import {
  agentMediaJobSchema,
  agentSsePayloadSchema,
  messageContextManifestSchema,
  type AgentMediaJob,
  type AgentSsePayload,
  type MessageContextManifest,
} from "@/shared/api/schemas/agentRun";

export type StartAgentRunBody = {
  threadId: string;
  scope: "global" | "post";
  chatId: string;
  postId?: string;
  postChatId?: string;
  userText: string;
  llmId?: string;
};

export async function startAgentRun(
  body: StartAgentRunBody,
  signal?: AbortSignal,
): Promise<{ id: string; sequence: number; assistant_message_id?: string }> {
  // Browser's IANA zone, e.g. "Europe/Moscow" — lets schedule_post resolve
  // relative phrasing ("сегодня через полчаса") in the user's local time
  // instead of the server's UTC.
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return apiRequest("/api/v1/ai/runs/", { method: "POST", body: { ...body, timezone }, signal });
}

export async function streamAgentRun(
  runId: string,
  onEvent: (event: AgentSsePayload) => void,
  signal?: AbortSignal,
  after = 0,
): Promise<void> {
  const query = after > 0 ? `?after=${after}` : "";
  await apiSseSubscribe(`/api/v1/ai/runs/${runId}/events/${query}`, {
    signal,
    onData(data) {
      const parsed = agentSsePayloadSchema.safeParse(data);
      if (parsed.success) onEvent(parsed.data);
    },
  });
}

export async function resumeAgentRun(
  runId: string,
  body: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return apiRequest(`/api/v1/ai/runs/${runId}/resume/`, { method: "POST", body });
}

export async function cancelAgentRun(runId: string, jobId?: string): Promise<void> {
  const query = jobId ? `?job_id=${encodeURIComponent(jobId)}` : "";
  await apiRequest(`/api/v1/ai/runs/${runId}/cancel/${query}`, { method: "POST" });
}

export async function getAgentMediaJob(
  runId: string,
  jobId: string,
): Promise<AgentMediaJob> {
  const data = await apiRequest<unknown>(`/api/v1/ai/runs/${runId}/media/${jobId}/`);
  return agentMediaJobSchema.parse(data);
}

export async function getAgentMessageContext(runId: string): Promise<MessageContextManifest> {
  const data = await apiRequest<unknown>(`/api/v1/ai/runs/${runId}/context/`);
  return messageContextManifestSchema.parse(data);
}

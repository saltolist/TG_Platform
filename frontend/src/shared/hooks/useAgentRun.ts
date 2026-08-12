import { useCallback, useEffect, useRef, useState } from "react";

import { streamAgentRun } from "@/shared/api/agentRuns";
import { apiRequest } from "@/shared/api/httpClient";
import { agentRunSchema, type AgentRun, type AgentSsePayload } from "../api/schemas/agentRun";

// Statuses from which a run never emits more events. "interrupted" is excluded
// on purpose: it resumes after a HITL decision and then streams again.
const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "cancelled"]);

type UseAgentRunOptions = {
  runId: string | null;
  enabled?: boolean;
  lastEventId?: number;
};

export function useAgentRun({ runId, enabled = true, lastEventId = 0 }: UseAgentRunOptions) {
  const [run, setRun] = useState<AgentRun | null>(null);
  const [events, setEvents] = useState<AgentSsePayload[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [lastSequence, setLastSequence] = useState(lastEventId);
  const lastSeqRef = useRef(lastEventId);

  const refresh = useCallback(async (): Promise<AgentRun | null> => {
    if (!runId || !enabled) return null;
    try {
      const json = await apiRequest<unknown>(`/api/v1/ai/runs/${runId}/`);
      const parsed = agentRunSchema.parse(json);
      setRun(parsed);
      return parsed;
    } catch {
      setError("run_fetch_failed");
      return null;
    }
  }, [enabled, runId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!runId || !enabled) return;
    const controller = new AbortController();
    const consume = async () => {
      while (!controller.signal.aborted) {
        try {
          await streamAgentRun(runId, (payload) => {
        if (payload.agent?.sequence) {
          lastSeqRef.current = payload.agent.sequence;
          setLastSequence(payload.agent.sequence);
        }
        setEvents((prev) => [...prev, payload]);
          }, controller.signal, lastSeqRef.current);
          const latest = await refresh();
          // Terminal runs emit no further events; the backend closes the SSE
          // stream immediately, so without this the loop reconnects every 500ms
          // forever (observed as endless GET events/?after=N in server logs).
          // "interrupted" is NOT terminal — the run resumes after a HITL
          // decision, so keep polling to pick up post-resume events.
          if (latest && TERMINAL_RUN_STATUSES.has(latest.status)) break;
        } catch {
          if (!controller.signal.aborted) setError("sse_disconnected");
        }
        if (!controller.signal.aborted) {
          await new Promise((resolve) => setTimeout(resolve, 500));
        }
      }
    };
    void consume();
    return () => controller.abort();
  }, [enabled, refresh, runId]);

  return { run, events, error, refresh, lastSequence };
}

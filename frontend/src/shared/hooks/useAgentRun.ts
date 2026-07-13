import { useCallback, useEffect, useRef, useState } from "react";

import { streamAgentRun } from "@/shared/api/agentRuns";
import { apiRequest } from "@/shared/api/httpClient";
import { agentRunSchema, type AgentRun, type AgentSsePayload } from "../api/schemas/agentRun";

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

  const refresh = useCallback(async () => {
    if (!runId || !enabled) return;
    try {
      const json = await apiRequest<unknown>(`/api/v1/ai/runs/${runId}/`);
      setRun(agentRunSchema.parse(json));
    } catch {
      setError("run_fetch_failed");
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
          await refresh();
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

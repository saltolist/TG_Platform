"use client";

import { useCallback, useEffect, useState } from "react";

import { getAgentMediaJob, resumeAgentRun } from "@/shared/api/agentRuns";
import type { AgentMediaJob, AgentProposal, AgentRun, AgentSsePayload } from "@/shared/api/schemas/agentRun";
import { useAgentRun } from "@/shared/hooks/useAgentRun";

type AgentRunStoreState = {
  runId: string | null;
  run: AgentRun | null;
  events: AgentSsePayload[];
  error: string | null;
  pendingProposal: AgentProposal | null;
  pendingMediaJob: AgentMediaJob | null;
};

export function useAgentRunStore(runId: string | null) {
  const { run, events, error, refresh } = useAgentRun({ runId, enabled: Boolean(runId) });
  const [pendingProposal, setPendingProposal] = useState<AgentProposal | null>(null);
  const [pendingMediaJob, setPendingMediaJob] = useState<AgentMediaJob | null>(null);

  const syncInterrupts = useCallback(() => {
    const interrupt = run?.current_interrupt as Record<string, unknown> | null | undefined;
    if (!interrupt) return;
    if (interrupt.type === "action_proposal") {
      const proposal = interrupt.proposal as AgentProposal & {
        payload?: Record<string, unknown>;
      };
      setPendingProposal({ ...proposal, preview: proposal.preview ?? proposal.payload });
      setPendingMediaJob(null);
    }
    if (interrupt.type === "media_cost") {
      const proposal = (interrupt.proposal ?? {}) as Record<string, unknown>;
      setPendingProposal(null);
      setPendingMediaJob({
        id: `cost-${runId}`,
        status: "awaiting_approval",
        stage: "cost",
        progress: 0,
        reserved_cost:
          typeof proposal.cost_ceiling === "number" ? proposal.cost_ceiling : null,
      });
    }
  }, [run?.current_interrupt, runId]);

  useEffect(() => {
    syncInterrupts();
  }, [syncInterrupts]);

  useEffect(() => {
    const interrupt = run?.current_interrupt as Record<string, unknown> | null | undefined;
    if (!runId || interrupt?.type !== "awaiting_job" || typeof interrupt.job_id !== "string") return;
    let active = true;
    const poll = async () => {
      try {
        const job = await getAgentMediaJob(runId, interrupt.job_id as string);
        if (active) setPendingMediaJob(job);
      } catch {
        // SSE reconnect and the next poll will retry.
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1500);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [run?.current_interrupt, runId]);

  const resume = useCallback(
    async (body: Record<string, unknown>) => {
      if (!runId) return null;
      const res = await resumeAgentRun(runId, body);
      setPendingProposal(null);
      setPendingMediaJob(null);
      await refresh();
      return res;
    },
    [refresh, runId],
  );

  const state: AgentRunStoreState = {
    runId,
    run,
    events,
    error,
    pendingProposal,
    pendingMediaJob,
  };

  return { ...state, refresh, resume, syncInterrupts };
}

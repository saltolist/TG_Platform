"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { getAgentMediaJob, resumeAgentRun } from "@/shared/api/agentRuns";
import type { AgentMediaJob, AgentProposal, AgentRun, AgentSsePayload } from "@/shared/api/schemas/agentRun";
import { useAgentRun } from "@/shared/hooks/useAgentRun";
import { useRepositories } from "@/app/providers/RepositoryProvider";
import { patchPostChatHistory } from "@/entities/post/lib/patchPostChatHistory";
import { patchGlobalChatHistory } from "@/entities/chat/lib/patchGlobalChatHistory";
import { updateLastVisibleAiMessage } from "@/shared/lib/chatPaths";
import type { ComposerScope } from "@/shared/types";

type AgentRunStoreState = {
  runId: string | null;
  run: AgentRun | null;
  events: AgentSsePayload[];
  error: string | null;
  pendingProposal: AgentProposal | null;
  pendingMediaJob: AgentMediaJob | null;
};

// Where to persist the proposal snapshot/decision so it survives a reload and
// renders in its own turn's slot instead of the always-at-the-bottom transient
// card store. Omitted entirely for scopes/turns that don't map to a chat
// history the caller can address (falls back to the old behavior).
export type AgentRunHistoryTarget =
  | { scope: "post"; postId: string; chatId: string }
  | { scope: "gchat" | "home"; chatId: string };

// Mirrors backend _action_result_text (workspace_graph.py) so this turn's
// text reflects what actually happened rather than a hardcoded "выполнено" —
// the real outcome (or lack of one) matters more here than message brevity.
function describeResumeResult(
  decision: "approve" | "reject",
  res: Record<string, unknown> | null,
): string {
  if (decision === "reject") return "Предложенное действие отклонено.";
  const applied = (res?.proposal as Record<string, unknown> | undefined)?.result as
    | Record<string, unknown>
    | undefined;
  if (!applied || typeof applied !== "object" || Object.keys(applied).length === 0) {
    return "Действие подтверждено (результат исполнения недоступен).";
  }
  const status = String(applied.status ?? "").trim();
  const postId = String(applied.post_id ?? "").trim();
  const tail = status ? ` (пост ${postId}, статус: ${status})` : "";
  return `Действие подтверждено и выполнено${tail}.`;
}

export function useAgentRunStore(
  runId: string | null,
  historyTarget?: AgentRunHistoryTarget | null,
) {
  const { run, events, error, refresh } = useAgentRun({ runId, enabled: Boolean(runId) });
  const [pendingProposal, setPendingProposal] = useState<AgentProposal | null>(null);
  const [pendingMediaJob, setPendingMediaJob] = useState<AgentMediaJob | null>(null);
  const { posts, chats } = useRepositories();
  const queryClient = useQueryClient();
  const recordedProposalIds = useRef<Set<string>>(new Set());

  const persistProposalToHistory = useCallback(
    (
      proposal: AgentProposal,
      decision: "approve" | "reject" | null,
      resultText?: string,
    ) => {
      if (!historyTarget) return;
      const apply = (history: Parameters<typeof updateLastVisibleAiMessage>[0]) =>
        updateLastVisibleAiMessage(history, (message) => ({
          ...message,
          proposal,
          proposalDecision: decision,
          // Mirrors action_hitl_node's answer_text (backend) so the same
          // "подтверждено и выполнено (пост X, статус Y)" / "отклонено" line
          // that used to only exist as an SSE `answer` event — easy to miss
          // if it arrives after this stream's consumer stopped listening —
          // lands directly in the turn the card belongs to.
          ...(resultText !== undefined ? { text: resultText } : null),
        }));
      if (historyTarget.scope === "post") {
        void patchPostChatHistory(queryClient, posts, historyTarget.postId, historyTarget.chatId, apply);
      } else {
        void patchGlobalChatHistory(queryClient, chats, historyTarget.chatId, apply);
      }
    },
    [historyTarget, posts, chats, queryClient],
  );

  const syncInterrupts = useCallback(() => {
    const interrupt = run?.current_interrupt as Record<string, unknown> | null | undefined;
    if (!interrupt) return;
    if (interrupt.type === "action_proposal") {
      const proposal = interrupt.proposal as AgentProposal & {
        payload?: Record<string, unknown>;
      };
      const resolved = { ...proposal, preview: proposal.preview ?? proposal.payload };
      setPendingProposal(resolved);
      setPendingMediaJob(null);
      if (!recordedProposalIds.current.has(resolved.id)) {
        recordedProposalIds.current.add(resolved.id);
        persistProposalToHistory(resolved, null);
      }
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
  }, [run?.current_interrupt, runId, persistProposalToHistory]);

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
      const decision = body.decision === "reject" ? "reject" : "approve";
      const proposalToRecord =
        pendingProposal && body.proposal_id === pendingProposal.id ? pendingProposal : null;
      const res = await resumeAgentRun(runId, body);
      if (proposalToRecord) {
        persistProposalToHistory(proposalToRecord, decision, describeResumeResult(decision, res));
      }
      setPendingProposal(null);
      setPendingMediaJob(null);
      await refresh();
      return res;
    },
    [refresh, runId, pendingProposal, persistProposalToHistory],
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

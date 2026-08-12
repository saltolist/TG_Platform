"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";

import { useAgentRunStore, type AgentRunHistoryTarget } from "@/app/model/store/agent-run-store";
import { useComposerReplyStore } from "@/app/model/store/composer-reply-store";
import type { AgentMediaJob, AgentProposal, AgentRun, AgentSsePayload } from "@/shared/api/schemas/agentRun";
import type { ComposerScope } from "@/shared/types";

type AgentRunContextValue = {
  runId: string | null;
  run: AgentRun | null;
  events: AgentSsePayload[];
  pendingProposal: AgentProposal | null;
  pendingMediaJob: AgentMediaJob | null;
  resume: (body: Record<string, unknown>) => Promise<Record<string, unknown> | null>;
};

const AgentRunContext = createContext<AgentRunContextValue | null>(null);

type ProviderProps = {
  scope: ComposerScope;
  postId?: string;
  chatId?: string;
  children: ReactNode;
};

// Wraps a screen's message list + AgentRunInterrupts so both read from a
// single useAgentRunStore subscription (one SSE stream per run, not one per
// consumer) — the inline proposal card in ChatAiMessage needs the same
// pendingProposal/resume the bottom-of-thread widget uses, to decide whether
// a persisted `message.proposal` is still awaiting a decision.
export function AgentRunProvider({ scope, postId, chatId, children }: ProviderProps) {
  const runId = useComposerReplyStore((state) => state.lastRunIdByScope[scope] ?? null);
  const historyTarget: AgentRunHistoryTarget | null = useMemo(() => {
    if (!chatId) return null;
    if (scope === "post") return postId ? { scope: "post", postId, chatId } : null;
    return { scope, chatId };
  }, [scope, postId, chatId]);
  const { run, events, pendingProposal, pendingMediaJob, resume } = useAgentRunStore(
    runId,
    historyTarget,
  );

  const value = useMemo(
    () => ({ runId, run, events, pendingProposal, pendingMediaJob, resume }),
    [runId, run, events, pendingProposal, pendingMediaJob, resume],
  );

  return <AgentRunContext.Provider value={value}>{children}</AgentRunContext.Provider>;
}

/** Returns null outside an AgentRunProvider — callers must treat that as "no live run". */
export function useAgentRunContext(): AgentRunContextValue | null {
  return useContext(AgentRunContext);
}

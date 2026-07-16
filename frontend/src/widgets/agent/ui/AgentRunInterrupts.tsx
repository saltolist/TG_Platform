"use client";

import { cancelAgentRun } from "@/shared/api/agentRuns";
import { useAgentRunContext } from "@/widgets/agent/model/AgentRunContext";
import { AgentActivityIndicator } from "@/widgets/agent/ui/AgentActivityIndicator";
import { MediaJobCard } from "@/widgets/agent/ui/MediaJobCard";

// Renders run-level status (activity indicator, media job, error) only. The
// proposal card itself is persisted into its own AI turn (agent-run-store)
// and rendered inline by ChatAiMessage, in that turn's slot in the thread —
// rendering it here too, at the bottom, would duplicate it.
export function AgentRunInterrupts() {
  const ctx = useAgentRunContext();

  if (!ctx || !ctx.runId) return null;
  const { runId, run, events, pendingMediaJob, resume } = ctx;

  return (
    <div className="agent-run-interrupts" aria-live="polite">
      <AgentActivityIndicator run={run} events={events} />
      {pendingMediaJob ? (
        <MediaJobCard
          job={pendingMediaJob}
          onApproveCost={
            pendingMediaJob.status === "awaiting_approval"
              ? () => void resume({ decision: "approve" })
              : undefined
          }
          onDiscard={
            pendingMediaJob.status === "awaiting_approval"
              ? () => void resume({ decision: "reject" })
              : undefined
          }
          onCancel={
            !["completed", "failed", "cancelled", "awaiting_approval"].includes(
              pendingMediaJob.status,
            )
              ? () => void cancelAgentRun(runId, pendingMediaJob.id)
              : undefined
          }
        />
      ) : null}
      {run?.error ? <div className="agent-run-error">{run.error}</div> : null}
    </div>
  );
}

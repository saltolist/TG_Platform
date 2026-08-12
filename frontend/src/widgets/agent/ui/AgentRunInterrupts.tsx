"use client";

import { cancelAgentRun } from "@/shared/api/agentRuns";
import { useAgentRunContext } from "@/widgets/agent/model/AgentRunContext";
import { MediaJobCard } from "@/widgets/agent/ui/MediaJobCard";

// Renders run-level status (media job, error) only. The "agent is working"
// activity phrase now lives inline in the streaming turn's own slot (rendered
// by ChatAiMessage via AiTypingIndicator), so there's a single dot indicator
// in the thread instead of a second one duplicated here at the bottom. The
// proposal card is likewise persisted into its own AI turn and rendered inline
// by ChatAiMessage — rendering it here too would duplicate it.
export function AgentRunInterrupts() {
  const ctx = useAgentRunContext();

  if (!ctx || !ctx.runId) return null;
  const { runId, run, pendingMediaJob, resume } = ctx;

  return (
    <div className="agent-run-interrupts" aria-live="polite">
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

"use client";

import { cancelAgentRun } from "@/shared/api/agentRuns";
import { useAgentRunStore } from "@/app/model/store/agent-run-store";
import { useComposerReplyStore } from "@/app/model/store/composer-reply-store";
import type { ComposerScope } from "@/shared/types";
import { AgentActivityIndicator } from "@/widgets/agent/ui/AgentActivityIndicator";
import { AgentProposalCard } from "@/widgets/agent/ui/AgentProposalCard";
import { MediaJobCard } from "@/widgets/agent/ui/MediaJobCard";

export function AgentRunInterrupts({ scope }: { scope: ComposerScope }) {
  const runId = useComposerReplyStore((state) => state.lastRunIdByScope[scope] ?? null);
  const { run, events, pendingProposal, pendingMediaJob, resume } = useAgentRunStore(runId);
  if (!runId) return null;

  return (
    <div className="agent-run-interrupts" aria-live="polite">
      <AgentActivityIndicator run={run} events={events} />
      {pendingProposal ? (
        <AgentProposalCard
          proposal={pendingProposal}
          onApprove={() =>
            void resume({
              decision: "approve",
              proposal_id: pendingProposal.id,
              payload_hash: pendingProposal.payload_hash,
            })
          }
          onReject={() =>
            void resume({
              decision: "reject",
              proposal_id: pendingProposal.id,
              payload_hash: pendingProposal.payload_hash,
            })
          }
        />
      ) : null}
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


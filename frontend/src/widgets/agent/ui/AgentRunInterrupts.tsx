"use client";

import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { cancelAgentRun } from "@/shared/api/agentRuns";
import { useAgentRunStore } from "@/app/model/store/agent-run-store";
import { useComposerReplyStore } from "@/app/model/store/composer-reply-store";
import { getCachedPost } from "@/entities/post/lib/getCachedPost";
import type { AgentProposal } from "@/shared/api/schemas/agentRun";
import type { ComposerScope } from "@/shared/types";
import { AgentActivityIndicator } from "@/widgets/agent/ui/AgentActivityIndicator";
import { AgentProposalCard } from "@/widgets/agent/ui/AgentProposalCard";
import { PostProposalCard, type ProposalDecision } from "@/widgets/agent/ui/PostProposalCard";
import { MediaJobCard } from "@/widgets/agent/ui/MediaJobCard";
import {
  POST_PROPOSAL_COMMANDS,
  proposalPostId,
} from "@/widgets/agent/lib/proposalPostPreview";

type DecidedProposal = {
  proposal: AgentProposal;
  decision: ProposalDecision;
  collapsed: boolean;
};

export function AgentRunInterrupts({ scope }: { scope: ComposerScope }) {
  const runId = useComposerReplyStore((state) => state.lastRunIdByScope[scope] ?? null);
  const { run, events, pendingProposal, pendingMediaJob, resume } = useAgentRunStore(runId);
  const queryClient = useQueryClient();
  const [decided, setDecided] = useState<DecidedProposal[]>([]);

  const isPostProposal = useCallback(
    (proposal: AgentProposal) => POST_PROPOSAL_COMMANDS.has(proposal.command),
    [],
  );

  const currentPostFor = useCallback(
    (proposal: AgentProposal) => {
      const postId = proposalPostId(proposal);
      return postId ? (getCachedPost(queryClient, postId) ?? null) : null;
    },
    [queryClient],
  );

  const decide = useCallback(
    (proposal: AgentProposal, decision: ProposalDecision) => {
      // Keep the card in the chat as a collapsed history entry after resume clears it.
      setDecided((prev) =>
        prev.some((d) => d.proposal.id === proposal.id)
          ? prev
          : [...prev, { proposal, decision, collapsed: true }],
      );
      void resume({
        decision,
        proposal_id: proposal.id,
        payload_hash: proposal.payload_hash,
      });
    },
    [resume],
  );

  const toggle = useCallback((id: string) => {
    setDecided((prev) =>
      prev.map((d) => (d.proposal.id === id ? { ...d, collapsed: !d.collapsed } : d)),
    );
  }, []);

  if (!runId) return null;

  // A resumed proposal briefly lingers in `pendingProposal`; hide it once decided.
  const pendingIsDecided = pendingProposal
    ? decided.some((d) => d.proposal.id === pendingProposal.id)
    : false;

  const renderProposal = (
    proposal: AgentProposal,
    decision: ProposalDecision | null,
    collapsed: boolean,
  ) =>
    isPostProposal(proposal) ? (
      <PostProposalCard
        key={proposal.id}
        proposal={proposal}
        currentPost={currentPostFor(proposal)}
        decision={decision}
        collapsed={collapsed}
        onDecide={(d) => decide(proposal, d)}
        onToggle={() => toggle(proposal.id)}
      />
    ) : (
      <AgentProposalCard
        key={proposal.id}
        proposal={proposal}
        onApprove={() => decide(proposal, "approve")}
        onReject={() => decide(proposal, "reject")}
      />
    );

  return (
    <div className="agent-run-interrupts" aria-live="polite">
      <AgentActivityIndicator run={run} events={events} />
      {decided.map((d) => renderProposal(d.proposal, d.decision, d.collapsed))}
      {pendingProposal && !pendingIsDecided
        ? renderProposal(pendingProposal, null, false)
        : null}
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

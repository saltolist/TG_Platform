"use client";

import type { AgentProposal } from "@/shared/api/schemas/agentRun";

type AgentProposalCardProps = {
  proposal: AgentProposal;
  onApprove: () => void;
  onReject: () => void;
  onEdit?: () => void;
};

export function AgentProposalCard({
  proposal,
  onApprove,
  onReject,
  onEdit,
}: AgentProposalCardProps) {
  return (
    <div className="agent-proposal-card" data-testid="agent-proposal-card">
      <div className="agent-proposal-card__title">Подтвердите действие: {proposal.command}</div>
      {proposal.warnings?.length ? (
        <ul className="agent-proposal-card__warnings">
          {proposal.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
      <pre className="agent-proposal-card__preview">
        {JSON.stringify(proposal.preview ?? {}, null, 2)}
      </pre>
      <div className="agent-proposal-card__actions">
        <button type="button" onClick={onApprove}>
          Подтвердить
        </button>
        <button type="button" onClick={onReject}>
          Отклонить
        </button>
        {onEdit ? (
          <button type="button" onClick={onEdit}>
            Изменить
          </button>
        ) : null}
      </div>
    </div>
  );
}

"use client";

import Image from "next/image";
import type { AgentMediaJob } from "@/shared/api/schemas/agentRun";

type MediaJobCardProps = {
  job: AgentMediaJob;
  onApproveCost?: () => void;
  onCancel?: () => void;
  onAttach?: () => void;
  onRegenerate?: () => void;
  onDiscard?: () => void;
};

export function MediaJobCard({
  job,
  onApproveCost,
  onCancel,
  onAttach,
  onRegenerate,
  onDiscard,
}: MediaJobCardProps) {
  const progress = Math.round((job.progress ?? 0) * 100);
  return (
    <div className="media-job-card" data-testid="media-job-card">
      <div className="media-job-card__title">Генерация медиа</div>
      <div className="media-job-card__status">
        {job.status} {job.stage ? `· ${job.stage}` : ""} · {progress}%
      </div>
      {typeof job.reserved_cost === "number" ? (
        <div className="media-job-card__cost">Оценка расхода: {job.reserved_cost}</div>
      ) : null}
      {job.preview_url ? (
        <Image
          unoptimized
          width={512}
          height={512}
          className="media-job-card__preview"
          src={job.preview_url}
          alt="preview"
        />
      ) : null}
      <div className="media-job-card__actions">
        {onApproveCost ? (
          <button type="button" onClick={onApproveCost}>
            Подтвердить расход
          </button>
        ) : null}
        {onCancel ? (
          <button type="button" onClick={onCancel}>
            Отменить
          </button>
        ) : null}
        {onAttach ? (
          <button type="button" onClick={onAttach}>
            Прикрепить
          </button>
        ) : null}
        {onRegenerate ? (
          <button type="button" onClick={onRegenerate}>
            Перегенерировать
          </button>
        ) : null}
        {onDiscard ? (
          <button type="button" onClick={onDiscard}>
            Отменить результат
          </button>
        ) : null}
      </div>
    </div>
  );
}

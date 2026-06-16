"use client";

import type { ReactNode } from "react";
import AiModelRow from "@/widgets/profile-settings/ui/ai/AiModelRow";
import { hasAvailableModelSlots } from "@/shared/lib/profile/filterAiModelOptions";
import type { LlmModel } from "@/shared/types";

type Props = {
  icon: ReactNode;
  title: string;
  models: LlmModel[];
  providerMap: Record<string, string[]>;
  addLabel: string;
  showActiveToggle?: boolean;
  showMultiToggle?: boolean;
  onModelChange: (idx: number, patch: Partial<LlmModel>) => void;
  onModelRemove: (idx: number) => void;
  onAdd: () => void;
  onApiKeyBlur?: () => void;
  showDivider?: boolean;
};

export default function AiModelListSection({
  icon,
  title,
  models,
  providerMap,
  addLabel,
  showActiveToggle = true,
  showMultiToggle = true,
  onModelChange,
  onModelRemove,
  onAdd,
  onApiKeyBlur,
  showDivider = true,
}: Props) {
  const canAddMore = hasAvailableModelSlots(providerMap, models);

  return (
    <>
      {showDivider ? <div className="profile-ai-divider" /> : null}
      <div className="profile-row profile-row--after-models">
        <div className="profile-label profile-label--with-icon">
          <span className="profile-label-icon" aria-hidden>
            {icon}
          </span>
          {title}
        </div>
      </div>
      <div className="profile-model-list">
        {models.map((m, idx) => (
          <AiModelRow
            key={m.id}
            rowIndex={idx}
            allModels={models}
            model={m}
            providerMap={providerMap}
            showActiveToggle={showActiveToggle}
            showMultiToggle={showMultiToggle}
            onChange={(patch) => onModelChange(idx, patch)}
            onRemove={() => onModelRemove(idx)}
            onApiKeyBlur={onApiKeyBlur}
          />
        ))}
        <button className="btn btn-ghost btn-sm" onClick={onAdd} type="button" disabled={!canAddMore}>
          {addLabel}
        </button>
      </div>
    </>
  );
}

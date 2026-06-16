"use client";

import { useMemo, useState } from "react";
import ModelPicker from "@/shared/ui/model-picker";
import { MessageTrashIcon } from "@/entities/message";
import { confirmDialog } from "@/shared/ui/dialog";
import {
  filterAvailableModels,
  filterAvailableProviders,
} from "@/shared/lib/profile/filterAiModelOptions";
import ProfileCheckbox from "@/widgets/profile-settings/ui/ProfileCheckbox";
import ProfileEyeIcon from "@/widgets/profile-settings/ui/ProfileEyeIcon";
import type { LlmModel } from "@/shared/types";

type Props = {
  rowIndex: number;
  allModels: LlmModel[];
  model: LlmModel;
  providerMap: Record<string, string[]>;
  showActiveToggle?: boolean;
  showMultiToggle?: boolean;
  onChange: (patch: Partial<LlmModel>) => void;
  onRemove?: () => void;
  onApiKeyBlur?: () => void;
};

export default function AiModelRow({
  rowIndex,
  allModels,
  model,
  providerMap,
  showActiveToggle = true,
  showMultiToggle = true,
  onChange,
  onRemove,
  onApiKeyBlur,
}: Props) {
  const [apiKeyVisible, setApiKeyVisible] = useState(false);
  const hasProvider = !!model.provider;

  const providerOptions = useMemo(() => {
    return filterAvailableProviders(providerMap, allModels, rowIndex).map((provider) => ({
      id: provider,
      label: provider,
    }));
  }, [allModels, providerMap, rowIndex]);

  const modelOptions = useMemo(() => {
    return filterAvailableModels(providerMap, allModels, rowIndex, model.provider).map(
      (modelName) => ({
        id: modelName,
        label: modelName,
      }),
    );
  }, [allModels, model.provider, providerMap, rowIndex]);

  return (
    <div className="profile-model-row">
      <div className="profile-model-pickers">
        <ModelPicker
          ariaLabel="Провайдер"
          className="profile-model-picker profile-model-provider"
          value={model.provider}
          options={providerOptions}
          placeholderLabel="Провайдер"
          placement="down"
          onChange={(provider) => {
            const nextModel = provider
              ? filterAvailableModels(providerMap, allModels, rowIndex, provider)[0] || ""
              : "";
            onChange({
              provider,
              model: nextModel,
              apiKey: provider ? model.apiKey : "",
              active: provider ? model.active : false,
              includeInMulti: provider ? model.includeInMulti : false,
            });
          }}
        />
        <ModelPicker
          ariaLabel="Модель"
          className="profile-model-picker profile-model-name"
          value={model.model}
          options={modelOptions}
          disabled={!hasProvider || modelOptions.length === 0}
          placeholderLabel="Выберите модель"
          placement="down"
          onChange={(value) => onChange({ model: value })}
        />
      </div>
      <div className="profile-model-key profile-model-key-wrap">
        <input
          className="profile-input profile-input-explicit profile-model-key-input"
          type={apiKeyVisible ? "text" : "password"}
          value={model.apiKey}
          placeholder="API key"
          disabled={!hasProvider}
          onChange={(e) => onChange({ apiKey: e.target.value })}
          onBlur={() => onApiKeyBlur?.()}
        />
        <button
          type="button"
          className="profile-api-key-toggle"
          disabled={!hasProvider}
          aria-label={apiKeyVisible ? "Скрыть API key" : "Показать API key"}
          title={apiKeyVisible ? "Скрыть API key" : "Показать API key"}
          onClick={() => setApiKeyVisible((value) => !value)}
        >
          <ProfileEyeIcon hidden={!apiKeyVisible} />
        </button>
      </div>
      <div className="profile-model-footer">
        <div className="profile-model-footer-checks">
          {showActiveToggle ? (
            <label className="profile-checkbox-label profile-model-multi">
              <ProfileCheckbox
                disabled={!hasProvider}
                checked={hasProvider && model.active}
                onChange={(e) => onChange({ active: e.target.checked })}
              />
              Активна
            </label>
          ) : null}
          {showMultiToggle ? (
            <label className="profile-checkbox-label profile-model-multi">
              <ProfileCheckbox
                disabled={!hasProvider}
                checked={hasProvider && model.includeInMulti}
                onChange={(e) => onChange({ includeInMulti: e.target.checked })}
              />
              В мультиответ
            </label>
          ) : null}
        </div>
        {onRemove ? (
          <button
            type="button"
            className="profile-model-remove"
            aria-label="Удалить модель"
            title="Удалить модель"
            onClick={() => {
              void (async () => {
                const label = model.model || model.provider || "модель";
                const ok = await confirmDialog({
                  message: `Удалить модель «${label}»?`,
                  confirmLabel: "Удалить",
                  destructive: true,
                });
                if (!ok) return;
                onRemove();
              })();
            }}
          >
            <MessageTrashIcon />
            <span className="profile-model-remove-label">Удалить</span>
          </button>
        ) : null}
      </div>
    </div>
  );
}

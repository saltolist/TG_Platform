"use client";

import { useMemo, useRef, useState } from "react";
import ModelPicker from "@/shared/ui/model-picker";
import { MessageTrashIcon } from "@/entities/message";
import {
  copyTextToClipboard,
  copyTextToClipboardFromPromise,
} from "@/shared/lib/clipboard/copyToClipboard";
import { confirmDialog } from "@/shared/ui/dialog";
import { useRepositories } from "@/app/providers/RepositoryProvider";
import {
  filterAvailableModels,
  filterAvailableProviders,
} from "@/shared/lib/profile/filterAiModelOptions";
import ProfileCheckbox from "@/widgets/profile-settings/ui/ProfileCheckbox";
import ProfileApiKeyCopyButton from "@/widgets/profile-settings/ui/ProfileApiKeyCopyButton";
import type { AiModelListField } from "@/shared/lib/profile/aiModelListField";
import {
  apiKeyForDisplay,
  canAttemptApiKeyCopy,
  isApiKeyPreview,
  isCopyableApiKey,
} from "@/shared/lib/profile/maskedApiKey";
import { reportMutationError } from "@/shared/ui/toast";
import type { LlmModel } from "@/shared/types";

type Props = {
  modelField: AiModelListField;
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
  modelField,
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
  const { profile } = useRepositories();
  const [editingKey, setEditingKey] = useState(false);
  const [draftKey, setDraftKey] = useState("");
  const [copied, setCopied] = useState(false);
  const [copying, setCopying] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasProvider = !!model.provider;
  const displayValue = editingKey ? draftKey : apiKeyForDisplay(model.apiKey);

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

  const markCopied = () => {
    if (copyTimer.current) clearTimeout(copyTimer.current);
    setCopied(true);
    copyTimer.current = setTimeout(() => {
      setCopied(false);
      copyTimer.current = null;
    }, 1500);
  };

  const handleCopy = () => {
    if (!canAttemptApiKeyCopy(model.apiKey) || copying) return;
    setCopying(true);

    const finish = (ok: boolean) => {
      setCopying(false);
      if (!ok) {
        reportMutationError(new Error("clipboard write failed"), "Не удалось скопировать API key");
        return;
      }
      markCopied();
    };

    if (isCopyableApiKey(model.apiKey)) {
      void copyTextToClipboard(model.apiKey).then(finish);
      return;
    }

    if (isApiKeyPreview(model.apiKey)) {
      void copyTextToClipboardFromPromise(() =>
        profile.revealAiModelApiKey(model.id, modelField).then((res) => res.apiKey),
      )
        .then(finish)
        .catch((error) => {
          setCopying(false);
          reportMutationError(error, "Не удалось скопировать API key");
        });
      return;
    }

    setCopying(false);
  };

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
          type="text"
          value={displayValue}
          placeholder="API key"
          disabled={!hasProvider}
          onFocus={() => {
            setEditingKey(true);
            setDraftKey(isApiKeyPreview(model.apiKey) ? "" : model.apiKey || "");
          }}
          onChange={(e) => {
            const next = e.target.value;
            setDraftKey(next);
            onChange({ apiKey: next });
          }}
          onBlur={() => {
            setEditingKey(false);
            if (isApiKeyPreview(model.apiKey) && !draftKey.trim()) {
              onChange({ apiKey: model.apiKey });
            }
            onApiKeyBlur?.();
          }}
        />
        <ProfileApiKeyCopyButton
          copied={copied}
          disabled={!hasProvider || !canAttemptApiKeyCopy(model.apiKey) || copying}
          onCopy={handleCopy}
        />
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

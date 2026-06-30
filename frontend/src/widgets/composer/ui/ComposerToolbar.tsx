"use client";

import AttachMenu from "./AttachMenu";
import ModelPicker, { BrainIcon, SearchIcon } from "@/shared/ui/model-picker";
import {
  formatLlmComposerButtonLabel,
  formatWebSearchComposerButtonLabel,
  formatWebSearchComposerLabel,
} from "@/shared/config/composer";
import type { ComposerAttachment, ComposerScope, LlmModel } from "@/shared/types";

type Props = {
  scope: ComposerScope;
  placement: "up" | "down";
  attachments: ComposerAttachment[];
  onAttach: (att: ComposerAttachment) => void;
  isMulti: boolean;
  llmOptions: LlmModel[];
  webOptions: LlmModel[];
  llmId: string;
  webId: string;
  /** Когда true — web-поиск встроен в LLM (Perplexity), отдельный пикер не нужен */
  webBuiltIn?: boolean;
  onLlmChange: (id: string) => void;
  onWebChange: (id: string) => void;
  onSubmit: () => void;
  isGenerating?: boolean;
  onStop?: () => void;
};

export default function ComposerToolbar({
  scope,
  placement,
  attachments,
  onAttach,
  isMulti,
  llmOptions,
  webOptions,
  llmId,
  webId,
  webBuiltIn = false,
  onLlmChange,
  onWebChange,
  onSubmit,
  isGenerating = false,
  onStop,
}: Props) {
  return (
    <div className="input-bottom">
      <div className="input-tools">
        <AttachMenu
          scope={scope}
          onAttach={onAttach}
          placement={placement}
          attachments={attachments}
        />
      </div>
      <div className="composer-mode">
        {!isMulti ? (
          <>
            <ModelPicker
              ariaLabel="LLM модель"
              className="composer-model-picker"
              icon={<BrainIcon />}
              value={llmId}
              options={llmOptions.map((m) => ({
                id: m.id,
                label: `${m.provider} / ${m.model}`,
              }))}
              buttonLabelFormatter={(opt) => {
                const m = llmOptions.find((row) => row.id === opt.id);
                return m ? formatLlmComposerButtonLabel(m.model) : opt.label;
              }}
              onChange={onLlmChange}
              disabled={llmOptions.length === 0}
              placeholderLabel="Нет LLM моделей"
              placement={placement}
            />
            {webBuiltIn ? (
              <div
                className="model-picker is-static composer-model-picker"
                title="Веб-поиск встроен в модель"
              >
                <div className="model-picker-btn" aria-disabled="true">
                  <span className="model-picker-icon">
                    <SearchIcon />
                  </span>
                  <span className="model-picker-label">Встроенный поиск</span>
                </div>
              </div>
            ) : (
              <ModelPicker
                ariaLabel="Web Search модель"
                className="composer-model-picker"
                icon={<SearchIcon />}
                value={webId}
                options={webOptions.map((m) => ({
                  id: m.id,
                  label: formatWebSearchComposerLabel(m.provider, m.model),
                }))}
                buttonLabelFormatter={(opt) => {
                  const m = webOptions.find((row) => row.id === opt.id);
                  return m
                    ? formatWebSearchComposerButtonLabel(m.provider, m.model)
                    : opt.label;
                }}
                onChange={onWebChange}
                emptyValue=""
                emptyLabel="Нет"
                placement={placement}
              />
            )}
          </>
        ) : (
          <div className="model-picker is-static is-disabled">
            <div className="model-picker-btn" aria-disabled="true">
              <span className="model-picker-icon">
                <BrainIcon />
              </span>
              <span className="model-picker-label">Мультиответ</span>
            </div>
          </div>
        )}
      </div>
      <div style={{ flex: 1 }} />
      {isGenerating ? (
        <button
          className="send-btn send-btn--stop"
          onClick={onStop}
          type="button"
          aria-label="Остановить генерацию"
          title="Остановить"
        >
          <span className="send-btn-stop-icon" aria-hidden />
        </button>
      ) : (
        <button className="send-btn" onClick={onSubmit} type="button" aria-label="Отправить">
          ↑
        </button>
      )}
    </div>
  );
}

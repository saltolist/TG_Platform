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
  onLlmChange: (id: string) => void;
  onWebChange: (id: string) => void;
  onSubmit: () => void;
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
  onLlmChange,
  onWebChange,
  onSubmit,
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
      <button className="send-btn" onClick={onSubmit} type="button">
        ↑
      </button>
    </div>
  );
}

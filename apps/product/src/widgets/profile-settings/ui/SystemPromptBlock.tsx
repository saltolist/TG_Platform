"use client";

import { useEffect, useRef, useState } from "react";
import { useProfileTextareaAutoResize } from "@/shared/lib/use-profile-textarea-auto-resize";
import { useModSaveUndo } from "@/shared/lib/hooks/useModSaveUndo";
import {
  domainActions,
  selectAiProfileConfig,
  selectSystemPromptSavedSnapshot,
  useDomainActions,
  useDomainDispatch,
  useDomainSelector,
  useUi,
  useUiStore,
} from "@/app/model/store";

export default function SystemPromptBlock({ active = true }: { active?: boolean }) {
  const scopeRef = useRef<HTMLDivElement | null>(null);
  const aiProfileConfig = useDomainSelector(selectAiProfileConfig);
  const systemPromptSavedSnapshot = useDomainSelector(selectSystemPromptSavedSnapshot);
  const dispatch = useDomainDispatch();
  const { applyPatch } = useDomainActions();
  const { setDirty } = useUi();
  const profilePromptDirty = useUiStore((s) => s.dirtyMap["profile-prompt"]);
  const [draft, setDraft] = useState(aiProfileConfig.systemPrompt);
  const dirty = draft !== systemPromptSavedSnapshot;
  const { ref: textareaRef, resize } = useProfileTextareaAutoResize(draft, active);

  useEffect(() => {
    if (!profilePromptDirty) {
      setDraft(systemPromptSavedSnapshot);
    }
  }, [profilePromptDirty, systemPromptSavedSnapshot]);

  useEffect(() => {
    setDirty("profile-prompt", dirty);
  }, [dirty, setDirty]);

  useEffect(() => {
    return () => setDirty("profile-prompt", false);
  }, [setDirty]);

  useEffect(() => {
    setDraft(aiProfileConfig.systemPrompt);
  }, [aiProfileConfig.systemPrompt, systemPromptSavedSnapshot]);

  const save = () => {
    if (!dirty) return;
    dispatch(domainActions.updateAiConfig({ ...aiProfileConfig, systemPrompt: draft }));
    applyPatch({ systemPromptSavedSnapshot: draft });
  };

  const cancel = () => {
    if (!dirty) return;
    setDraft(systemPromptSavedSnapshot);
  };

  useModSaveUndo({ active, dirty, onSave: save, scopeRef });

  return (
    <div className="profile-section" ref={scopeRef}>
      <div className="profile-section-title">Системный промпт</div>
      <div className="profile-row">
        <textarea
          ref={textareaRef}
          className="profile-input profile-input-explicit profile-textarea profile-system-prompt-textarea"
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            requestAnimationFrame(resize);
          }}
        />
      </div>
      <div className="profile-action-buttons profile-action-buttons--ai">
        <button className="btn btn-primary" disabled={!dirty} onClick={save} type="button">
          Сохранить
        </button>
        {dirty ? (
          <button className="btn btn-ghost" onClick={cancel} type="button">
            Отменить
          </button>
        ) : null}
      </div>
    </div>
  );
}

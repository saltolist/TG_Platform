"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useUpdateAiProfile } from "@/entities/channel";
import { useProfileTextareaAutoResize } from "@/shared/lib/use-profile-textarea-auto-resize";
import { useModSaveUndo } from "@/shared/lib/hooks/useModSaveUndo";
import { normalizeAiProfileConfig } from "@/shared/lib/profile/aiModelsSnapshot";
import { reportMutationError, showToast } from "@/shared/ui/toast";
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
import { useProfileDraftStore } from "@/app/model/store/profile-draft-store";

export default function SystemPromptBlock({ active = true }: { active?: boolean }) {
  const scopeRef = useRef<HTMLDivElement | null>(null);
  const aiProfileConfig = useDomainSelector(selectAiProfileConfig);
  const systemPromptSavedSnapshot = useDomainSelector(selectSystemPromptSavedSnapshot);
  const dispatch = useDomainDispatch();
  const { applyPatch } = useDomainActions();
  const { setDirty } = useUi();
  const updateAiProfile = useUpdateAiProfile();
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

  const save = useCallback(async () => {
    if (!dirty) return;

    const state = useProfileDraftStore.getState();
    if (!state.hydrated) return;

    const nextCfg = normalizeAiProfileConfig({
      ...state.aiProfileConfig,
      systemPrompt: draft,
    });
    const previousSnapshot = state.systemPromptSavedSnapshot;

    dispatch(domainActions.updateAiConfig(nextCfg));
    applyPatch({ systemPromptSavedSnapshot: draft });

    try {
      const saved = await updateAiProfile.mutateAsync(nextCfg);
      const savedPrompt = normalizeAiProfileConfig(saved).systemPrompt;
      applyPatch({ systemPromptSavedSnapshot: savedPrompt });
      dispatch(domainActions.updateAiConfig(normalizeAiProfileConfig(saved)));
      showToast({ message: "Системный промпт сохранён", variant: "info" });
    } catch (error) {
      applyPatch({ systemPromptSavedSnapshot: previousSnapshot });
      dispatch(
        domainActions.updateAiConfig({
          ...state.aiProfileConfig,
          systemPrompt: previousSnapshot,
        }),
      );
      setDraft(previousSnapshot);
      reportMutationError(error, "Не удалось сохранить системный промпт");
    }
  }, [applyPatch, dirty, dispatch, draft, updateAiProfile]);

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
        <button
          className="btn btn-primary"
          disabled={!dirty || updateAiProfile.isPending}
          onClick={() => void save()}
          type="button"
        >
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

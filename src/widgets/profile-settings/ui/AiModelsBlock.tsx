"use client";

import AiModelListSection from "@/widgets/profile-settings/ui/ai/AiModelListSection";
import ProfileCheckbox from "@/widgets/profile-settings/ui/ProfileCheckbox";
import { BrainIcon, ImageGenIcon, SearchIcon, VisionIcon } from "@/shared/ui/model-picker";
import {
  IMAGE_GENERATION_PROVIDER_MODELS,
  LLM_PROVIDER_MODELS,
  VISION_PROVIDER_MODELS,
  WEB_SEARCH_PROVIDER_MODELS,
} from "@/shared/config/composer";
import { useAiModelsBlock } from "@/widgets/profile-settings/model/useAiModelsBlock";

export default function AiModelsBlock() {
  const ai = useAiModelsBlock();
  const { cfg } = ai;

  return (
    <div className="profile-section profile-ai-engine-section">
      <div className="profile-section-title">ИИ-движок</div>

      <AiModelListSection
        icon={<BrainIcon />}
        title="LLM-модели"
        models={cfg.llmModels}
        providerMap={LLM_PROVIDER_MODELS}
        addLabel="Добавить LLM модель"
        showDivider={false}
        onModelChange={(idx, patch) =>
          ai.setLlms(cfg.llmModels.map((row, i) => (i === idx ? { ...row, ...patch } : row)))
        }
        onModelRemove={(idx) => ai.setLlms(cfg.llmModels.filter((_, i) => i !== idx))}
        onAdd={ai.addLlm}
        onApiKeyBlur={() => void ai.flushSave()}
      />

      <AiModelListSection
        icon={<SearchIcon />}
        title="Web Search модели"
        models={cfg.webSearchModels}
        providerMap={WEB_SEARCH_PROVIDER_MODELS}
        addLabel="Добавить Web Search модель"
        onModelChange={(idx, patch) =>
          ai.setWebs(cfg.webSearchModels.map((row, i) => (i === idx ? { ...row, ...patch } : row)))
        }
        onModelRemove={(idx) => ai.setWebs(cfg.webSearchModels.filter((_, i) => i !== idx))}
        onAdd={ai.addWeb}
        onApiKeyBlur={() => void ai.flushSave()}
      />

      <AiModelListSection
        icon={<BrainIcon />}
        title="Оркестратор"
        models={cfg.orchestratorModels}
        providerMap={LLM_PROVIDER_MODELS}
        addLabel="Добавить модель оркестратора"
        showMultiToggle={false}
        onModelChange={(idx, patch) =>
          ai.setOrchestrators(ai.updateExclusiveModel(cfg.orchestratorModels, idx, patch))
        }
        onModelRemove={(idx) => ai.setOrchestrators(cfg.orchestratorModels.filter((_, i) => i !== idx))}
        onAdd={ai.addOrchestrator}
        onApiKeyBlur={() => void ai.flushSave()}
      />

      <AiModelListSection
        icon={<SearchIcon />}
        title="Web Reasoner"
        models={cfg.webReasonerModels}
        providerMap={LLM_PROVIDER_MODELS}
        addLabel="Добавить Web Reasoner"
        showMultiToggle={false}
        onModelChange={(idx, patch) =>
          ai.setWebReasoners(ai.updateExclusiveModel(cfg.webReasonerModels, idx, patch))
        }
        onModelRemove={(idx) => ai.setWebReasoners(cfg.webReasonerModels.filter((_, i) => i !== idx))}
        onAdd={ai.addWebReasoner}
        onApiKeyBlur={() => void ai.flushSave()}
      />

      <AiModelListSection
        icon={<BrainIcon />}
        title="RAG Reasoner"
        models={cfg.ragReasonerModels}
        providerMap={LLM_PROVIDER_MODELS}
        addLabel="Добавить RAG Reasoner"
        showMultiToggle={false}
        onModelChange={(idx, patch) =>
          ai.setRagReasoners(ai.updateExclusiveModel(cfg.ragReasonerModels, idx, patch))
        }
        onModelRemove={(idx) => ai.setRagReasoners(cfg.ragReasonerModels.filter((_, i) => i !== idx))}
        onAdd={ai.addRagReasoner}
        onApiKeyBlur={() => void ai.flushSave()}
      />

      <AiModelListSection
        icon={<VisionIcon />}
        title="Модели компьютерного зрения"
        models={cfg.visionModels}
        providerMap={VISION_PROVIDER_MODELS}
        addLabel="Добавить модель компьютерного зрения"
        showMultiToggle={false}
        onModelChange={(idx, patch) =>
          ai.setVisionModels(cfg.visionModels.map((row, i) => (i === idx ? { ...row, ...patch } : row)))
        }
        onModelRemove={(idx) => ai.setVisionModels(cfg.visionModels.filter((_, i) => i !== idx))}
        onAdd={ai.addVision}
        onApiKeyBlur={() => void ai.flushSave()}
      />

      <AiModelListSection
        icon={<ImageGenIcon />}
        title="Модели генерации изображений"
        models={cfg.imageGenerationModels}
        providerMap={IMAGE_GENERATION_PROVIDER_MODELS}
        addLabel="Добавить модель генерации изображений"
        showMultiToggle={false}
        onModelChange={(idx, patch) =>
          ai.setImageGenerationModels(
            cfg.imageGenerationModels.map((row, i) => (i === idx ? { ...row, ...patch } : row)),
          )
        }
        onModelRemove={(idx) =>
          ai.setImageGenerationModels(cfg.imageGenerationModels.filter((_, i) => i !== idx))
        }
        onAdd={ai.addImageGeneration}
        onApiKeyBlur={() => void ai.flushSave()}
      />

      <div className="profile-ai-divider" />
      <div className="profile-multi-block profile-row--after-models">
        <div className="profile-label">Мультиответ</div>
        <label className="profile-checkbox-label profile-multi-toggle">
          <ProfileCheckbox
            disabled={!ai.multiEligible}
            checked={cfg.multiResponseEnabled && ai.multiEligible}
            onChange={(e) => ai.update({ ...cfg, multiResponseEnabled: e.target.checked && ai.multiEligible })}
          />
          <span className={!ai.multiEligible ? "toggle-disabled-strike" : ""}>Включить</span>
        </label>
        <div className="profile-val profile-ai-multi-hint">
          При включенном мультиответе в поле ввода показывается один заблокированный режим.
          {ai.multiEligible ? null : (
            <>
              {" "}
              Сейчас доступно пар: <b>{ai.multiResponsePairs.length}</b>, нужно минимум 2.
            </>
          )}
        </div>
      </div>
    </div>
  );
}

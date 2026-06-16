"use client";

import { useRef, type ReactNode } from "react";
import ProfileEyeIcon from "@/widgets/profile-settings/ui/ProfileEyeIcon";
import type { TelegramProfileConfig } from "@/shared/types";
import { useModSaveUndo } from "@/shared/lib/hooks/useModSaveUndo";

type Props = {
  active?: boolean;
  cfg: TelegramProfileConfig;
  apiChangedFromSaved: boolean;
  apiIdMissing: boolean;
  apiHashMissing: boolean;
  credentialsFlashNonce: number;
  apiHashVisible: boolean;
  onApiIdChange: (apiId: string) => void;
  onApiHashChange: (apiHash: string) => void;
  onToggleApiHashVisible: () => void;
  onSave: () => void;
  onCancel: () => void;
};

function TelegramApiFieldLabel({
  children,
  showRequired,
  flashNonce,
}: {
  children: ReactNode;
  showRequired: boolean;
  flashNonce: number;
}) {
  return (
    <div className="profile-label">
      {children}
      {showRequired ? (
        <span
          key={flashNonce}
          className={`telegram-api-required-mark${flashNonce > 0 ? " telegram-api-required-mark--flash" : ""}`}
          aria-hidden
        >
          {" !"}
        </span>
      ) : null}
    </div>
  );
}

export default function TelegramApiCredentialsSection({
  active = true,
  cfg,
  apiChangedFromSaved,
  apiIdMissing,
  apiHashMissing,
  credentialsFlashNonce,
  apiHashVisible,
  onApiIdChange,
  onApiHashChange,
  onToggleApiHashVisible,
  onSave,
  onCancel,
}: Props) {
  const scopeRef = useRef<HTMLDivElement | null>(null);
  useModSaveUndo({ active, dirty: apiChangedFromSaved, onSave, scopeRef });

  return (
    <div
      className={`telegram-api-credentials${apiChangedFromSaved ? " telegram-api-credentials--dirty" : ""}`}
      ref={scopeRef}
    >
      <div className="profile-row telegram-api-id-row">
        <TelegramApiFieldLabel showRequired={apiIdMissing} flashNonce={credentialsFlashNonce}>
          api_id
        </TelegramApiFieldLabel>
        <input
          className="profile-input profile-input-explicit telegram-input telegram-api-id-input"
          value={cfg.apiId}
          placeholder="12345678"
          onChange={(e) => onApiIdChange(e.target.value)}
        />
      </div>

      <div className="profile-row telegram-api-hash-row">
        <TelegramApiFieldLabel showRequired={apiHashMissing} flashNonce={credentialsFlashNonce}>
          api_hash
        </TelegramApiFieldLabel>
        <div className="telegram-input-wrap telegram-api-hash-input-wrap">
          <input
            className="profile-input profile-input-explicit telegram-input telegram-api-hash-input telegram-input-with-toggle"
            type={apiHashVisible ? "text" : "password"}
            value={cfg.apiHash}
            placeholder="••••••••••••••••"
            onChange={(e) => onApiHashChange(e.target.value)}
          />
          <button
            type="button"
            className="profile-api-key-toggle"
            aria-label={apiHashVisible ? "Скрыть api_hash" : "Показать api_hash"}
            title={apiHashVisible ? "Скрыть api_hash" : "Показать api_hash"}
            onClick={onToggleApiHashVisible}
          >
            <ProfileEyeIcon hidden={!apiHashVisible} />
          </button>
        </div>
      </div>

      <div className="profile-action-buttons profile-action-buttons--ai telegram-api-actions">
        <button
          className="btn btn-primary telegram-api-action-btn"
          type="button"
          disabled={!apiChangedFromSaved}
          onClick={onSave}
        >
          Сохранить
        </button>
        <button
          className="btn btn-ghost telegram-api-action-btn telegram-api-action-btn--cancel"
          type="button"
          disabled={!apiChangedFromSaved}
          onClick={onCancel}
        >
          Отменить
        </button>
      </div>
    </div>
  );
}

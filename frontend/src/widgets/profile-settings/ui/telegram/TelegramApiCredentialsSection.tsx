"use client";

import { useRef, type ReactNode } from "react";
import type { TelegramProfileConfig } from "@/shared/types";
import { useModSaveUndo } from "@/shared/lib/hooks/useModSaveUndo";
import TelegramSecretCopyButton from "@/widgets/profile-settings/ui/telegram/TelegramSecretCopyButton";
import { useSecretFieldEdit } from "@/widgets/profile-settings/ui/telegram/useSecretFieldEdit";

type Props = {
  active?: boolean;
  cfg: TelegramProfileConfig;
  apiChangedFromSaved: boolean;
  apiIdMissing: boolean;
  apiHashMissing: boolean;
  credentialsFlashNonce: number;
  saving?: boolean;
  onApiIdChange: (apiId: string) => void;
  onApiHashChange: (apiHash: string) => void;
  onSave: () => void | Promise<void>;
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
  saving = false,
  onApiIdChange,
  onApiHashChange,
  onSave,
  onCancel,
}: Props) {
  const scopeRef = useRef<HTMLDivElement | null>(null);
  useModSaveUndo({ active, dirty: apiChangedFromSaved, onSave, scopeRef });
  const apiHashField = useSecretFieldEdit(cfg.apiHash, onApiHashChange);

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
            type="text"
            placeholder="••••••••••••••••"
            {...apiHashField.inputProps}
          />
          <TelegramSecretCopyButton
            value={cfg.apiHash}
            field="apiHash"
            disabled={!cfg.apiHash.trim()}
            ariaLabel="Скопировать api_hash"
          />
        </div>
      </div>

      <div className="profile-action-buttons profile-action-buttons--ai telegram-api-actions">
        <button
          className="btn btn-primary telegram-api-action-btn"
          type="button"
          disabled={!apiChangedFromSaved || saving}
          onClick={() => void onSave()}
        >
          Сохранить
        </button>
        <button
          className="btn btn-ghost telegram-api-action-btn telegram-api-action-btn--cancel"
          type="button"
          disabled={!apiChangedFromSaved || saving}
          onClick={onCancel}
        >
          Отменить
        </button>
      </div>
    </div>
  );
}

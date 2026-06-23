"use client";

import type { TelegramProfileConfig } from "@/shared/types";
import { formatStoredDate } from "@/shared/lib/helpers";
import TelegramSecretCopyButton from "@/widgets/profile-settings/ui/telegram/TelegramSecretCopyButton";
import { useSecretFieldEdit } from "@/widgets/profile-settings/ui/telegram/useSecretFieldEdit";

type Props = {
  cfg: TelegramProfileConfig;
  isBotConnected: boolean;
  addBotDisabled: boolean;
  connecting?: boolean;
  onBotTokenChange: (token: string) => void;
  onConnectBot: () => void | Promise<void>;
};

export default function TelegramOmnibotSection({
  cfg,
  isBotConnected,
  addBotDisabled,
  connecting = false,
  onBotTokenChange,
  onConnectBot,
}: Props) {
  const botTokenField = useSecretFieldEdit(cfg.botApiToken, onBotTokenChange);

  return (
    <div className="telegram-omnibot-section">
      <div className="telegram-omnibot-title">Омниканальный бот</div>

      <div className="telegram-omnibot-desktop">
        <div className="profile-row telegram-omnibot-desktop-row">
          <div className="profile-label">API-токен</div>
          <div className="telegram-omnibot-desktop-fields">
            <div className="telegram-input-wrap telegram-omnibot-token-wrap">
              <input
                className="profile-input profile-input-explicit telegram-input telegram-input-with-toggle"
                type="text"
                placeholder="••••••••••••••••"
                {...botTokenField.inputProps}
              />
              <TelegramSecretCopyButton
                value={cfg.botApiToken}
                field="botApiToken"
                disabled={!cfg.botApiToken.trim()}
                ariaLabel="Скопировать API-токен"
              />
            </div>
            <button
              className="btn btn-ghost telegram-inline-button"
              disabled={addBotDisabled || connecting}
              onClick={() => void onConnectBot()}
              type="button"
            >
              Добавить
            </button>
          </div>
        </div>
      </div>

      <div className="telegram-omnibot-mobile">
        <div className="profile-row telegram-bot-token-row">
          <div className="profile-label">API-токен</div>
          <div className="telegram-inline-field-row">
            <div className="telegram-input-wrap">
              <input
                className="profile-input profile-input-explicit telegram-input telegram-input-with-toggle"
                type="text"
                placeholder="••••••••••••••••"
                {...botTokenField.inputProps}
              />
              <TelegramSecretCopyButton
                value={cfg.botApiToken}
                field="botApiToken"
                disabled={!cfg.botApiToken.trim()}
                ariaLabel="Скопировать API-токен"
              />
            </div>
            <button
              className="btn btn-ghost telegram-inline-button"
              disabled={addBotDisabled || connecting}
              onClick={() => void onConnectBot()}
              type="button"
            >
              Добавить
            </button>
          </div>
        </div>
      </div>

      {isBotConnected ? (
        <div className="telegram-sync-card telegram-omnibot-card">
          <div>
            <div className="profile-label">Подключённый бот</div>
            <div className="profile-val">{cfg.botUsername}</div>
          </div>
          <div>
            <div className="profile-label">Последняя активность</div>
            <div className="profile-val">{formatStoredDate(cfg.botLastActivity) || "—"}</div>
          </div>
          <div>
            <div className="profile-label">Сообщений</div>
            <div className="profile-val">{cfg.botMessageCount.toLocaleString("ru-RU")}</div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

"use client";

import ProfileEyeIcon from "@/widgets/profile-settings/ui/ProfileEyeIcon";
import type { TelegramProfileConfig } from "@/shared/types";

type Props = {
  cfg: TelegramProfileConfig;
  isBotConnected: boolean;
  botApiTokenVisible: boolean;
  addBotDisabled: boolean;
  onBotTokenChange: (token: string) => void;
  onToggleBotTokenVisible: () => void;
  onConnectBot: () => void;
};

export default function TelegramOmnibotSection({
  cfg,
  isBotConnected,
  botApiTokenVisible,
  addBotDisabled,
  onBotTokenChange,
  onToggleBotTokenVisible,
  onConnectBot,
}: Props) {
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
                type={botApiTokenVisible ? "text" : "password"}
                value={cfg.botApiToken}
                placeholder="••••••••••••••••"
                onChange={(e) => onBotTokenChange(e.target.value)}
              />
              <button
                type="button"
                className="profile-api-key-toggle"
                aria-label={botApiTokenVisible ? "Скрыть API-токен" : "Показать API-токен"}
                title={botApiTokenVisible ? "Скрыть API-токен" : "Показать API-токен"}
                onClick={onToggleBotTokenVisible}
              >
                <ProfileEyeIcon hidden={!botApiTokenVisible} />
              </button>
            </div>
            <button
              className="btn btn-ghost telegram-inline-button"
              disabled={addBotDisabled}
              onClick={onConnectBot}
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
                type={botApiTokenVisible ? "text" : "password"}
                value={cfg.botApiToken}
                placeholder="••••••••••••••••"
                onChange={(e) => onBotTokenChange(e.target.value)}
              />
              <button
                type="button"
                className="profile-api-key-toggle"
                aria-label={botApiTokenVisible ? "Скрыть API-токен" : "Показать API-токен"}
                title={botApiTokenVisible ? "Скрыть API-токен" : "Показать API-токен"}
                onClick={onToggleBotTokenVisible}
              >
                <ProfileEyeIcon hidden={!botApiTokenVisible} />
              </button>
            </div>
            <button
              className="btn btn-ghost telegram-inline-button"
              disabled={addBotDisabled}
              onClick={onConnectBot}
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
            <div className="profile-val">{cfg.botLastActivity}</div>
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

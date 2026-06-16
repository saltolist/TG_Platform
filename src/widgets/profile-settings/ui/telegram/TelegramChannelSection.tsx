"use client";

import type { TelegramProfileConfig } from "@/shared/types";

type Props = {
  cfg: TelegramProfileConfig;
  isAuthorized: boolean;
  isConnected: boolean;
  connectChannelDisabled: boolean;
  onChannelChange: (channel: string) => void;
  onConnectChannel: () => void;
};

export default function TelegramChannelSection({
  cfg,
  isAuthorized,
  isConnected,
  connectChannelDisabled,
  onChannelChange,
  onConnectChannel,
}: Props) {
  return (
    <div className={`telegram-channel-section${!isAuthorized ? " hidden" : ""}`}>
      <div className="telegram-channel-desktop">
        <div className="profile-row telegram-channel-desktop-row">
          <div className="profile-label">Канал</div>
          <div className="telegram-channel-desktop-fields">
            <input
              className="profile-input profile-input-explicit telegram-input telegram-channel-input"
              value={cfg.channel}
              placeholder="@channel или -100..."
              onChange={(e) => onChannelChange(e.target.value)}
            />
            <button
              className="btn btn-ghost telegram-inline-button"
              disabled={connectChannelDisabled}
              onClick={onConnectChannel}
              type="button"
            >
              Подключить канал
            </button>
          </div>
        </div>
      </div>
      <div className="telegram-channel-mobile">
        <div className="profile-row telegram-channel-row">
          <div className="profile-label">Канал</div>
          <div className="telegram-inline-field-row">
            <input
              className="profile-input profile-input-explicit telegram-input"
              value={cfg.channel}
              placeholder="@channel или -100..."
              onChange={(e) => onChannelChange(e.target.value)}
            />
            <button
              className="btn btn-ghost telegram-inline-button"
              disabled={connectChannelDisabled}
              onClick={onConnectChannel}
              type="button"
            >
              Подключить
            </button>
          </div>
        </div>
      </div>

      {isConnected ? (
        <div className="telegram-sync-card telegram-channel-card">
          <div>
            <div className="profile-label">Подключённый канал</div>
            <div className="profile-val">
              {cfg.channelTitle} · {cfg.channel}
            </div>
          </div>
          <div>
            <div className="profile-label">Последняя синхронизация</div>
            <div className="profile-val">{cfg.lastSync}</div>
          </div>
          <div>
            <div className="profile-label">Импортировано постов</div>
            <div className="profile-val">{cfg.importedPosts}</div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

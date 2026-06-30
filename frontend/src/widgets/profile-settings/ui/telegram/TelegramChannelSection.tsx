"use client";

import type { TelegramProfileConfig } from "@/shared/types";
import { formatStoredDate } from "@/shared/lib/helpers";
import { getConnectedChannelDisplayName } from "@/shared/lib/channel/normalizeChannelHandle";

type Props = {
  cfg: TelegramProfileConfig;
  isAuthorized: boolean;
  isConnected: boolean;
  connectChannelDisabled: boolean;
  connecting: boolean;
  importing: boolean;
  onChannelChange: (channel: string) => void;
  onConnectChannel: () => void;
};

function getImportStatusLabel(cfg: TelegramProfileConfig, importing: boolean): string {
  if (importing || cfg.importStatus === "importing") return "Импортируем историю…";
  if (cfg.importStatus === "error") {
    return cfg.importError || "Не удалось импортировать историю постов";
  }
  if (cfg.importStatus === "done" && cfg.importedPosts > 0) {
    return `Импортировано ${cfg.importedPosts} постов`;
  }
  return "—";
}

function getLiveSyncStatusLabel(cfg: TelegramProfileConfig): string {
  if (cfg.syncStatus === "listening") return "Слушаем канал…";
  if (cfg.syncStatus === "error") {
    return cfg.syncError || "Ошибка live-синхронизации";
  }
  return "—";
}

export default function TelegramChannelSection({
  cfg,
  isAuthorized,
  isConnected,
  connectChannelDisabled,
  connecting,
  importing,
  onChannelChange,
  onConnectChannel,
}: Props) {
  const channelBusy = connecting || importing;
  return (
    <div className={`telegram-channel-section${!isAuthorized ? " hidden" : ""}`}>
      <div className="telegram-channel-desktop">
        <div className="profile-row telegram-channel-desktop-row">
          <div className="profile-label">Канал</div>
          <div className="telegram-channel-desktop-fields">
            <input
              className="profile-input profile-input-explicit telegram-input telegram-channel-input"
              value={cfg.channel}
              placeholder="@channel, t.me/+… или -100…"
              disabled={channelBusy}
              onChange={(e) => onChannelChange(e.target.value)}
            />
            <button
              className="btn btn-ghost telegram-inline-button"
              disabled={connectChannelDisabled || channelBusy}
              onClick={onConnectChannel}
              type="button"
            >
              {connecting ? "Проверяем…" : importing ? "Импорт…" : "Подключить канал"}
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
              placeholder="@channel, t.me/+… или -100…"
              disabled={channelBusy}
              onChange={(e) => onChannelChange(e.target.value)}
            />
            <button
              className="btn btn-ghost telegram-inline-button"
              disabled={connectChannelDisabled || channelBusy}
              onClick={onConnectChannel}
              type="button"
            >
              {connecting ? "Проверяем…" : importing ? "Импорт…" : "Подключить"}
            </button>
          </div>
        </div>
      </div>

      {isConnected ? (
        <div className="telegram-sync-card telegram-channel-card">
          <div>
            <div className="profile-label">Подключённый канал</div>
            <div className="profile-val">
              {getConnectedChannelDisplayName(cfg.channelTitle, cfg.channel)}
            </div>
          </div>
          <div>
            <div className="profile-label">Последняя синхронизация</div>
            <div className="profile-val">{formatStoredDate(cfg.lastSync) || "—"}</div>
          </div>
          <div>
            <div className="profile-label">Импорт истории</div>
            <div className="profile-val">{getImportStatusLabel(cfg, importing)}</div>
          </div>
          <div>
            <div className="profile-label">Live-синхронизация</div>
            <div className="profile-val">{getLiveSyncStatusLabel(cfg)}</div>
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

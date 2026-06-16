"use client";

type Props = {
  status: { className: string; text: string };
  isAuthorized: boolean;
  isConnected: boolean;
  syncing: boolean;
  onReset: () => void;
};

export default function TelegramStatusHeader({
  status,
  isAuthorized,
  isConnected,
  syncing,
  onReset,
}: Props) {
  return (
    <>
      <div className="telegram-status-row">
        <div>
          <div className="profile-label">Статус</div>
          <div className={`telegram-status ${status.className}`}>
            <span className="telegram-status-dot" />
            {status.text}
          </div>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={onReset} type="button">
          Сбросить настройки
        </button>
      </div>

      <div className="telegram-steps">
        <div className={`telegram-step ${isAuthorized ? "done" : "active"}`}>
          <span>1</span>
          <div>
            <b>Авторизация аккаунта</b>
            <small>api_id, api_hash и телефон для MTProto-сессии</small>
          </div>
        </div>
        <div className={`telegram-step ${isAuthorized ? (isConnected ? "done" : "active") : ""}`}>
          <span>2</span>
          <div>
            <b>Подключение канала</b>
            <small>username, invite link или id канала</small>
          </div>
        </div>
        <div className={`telegram-step ${syncing ? "active syncing" : isConnected ? "done" : ""}`}>
          <span>3</span>
          <div>
            <b>Синхронизация</b>
            <small>история постов и новые события</small>
          </div>
        </div>
      </div>
    </>
  );
}

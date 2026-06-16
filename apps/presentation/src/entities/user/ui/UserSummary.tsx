"use client";

import type { UserPasswordFlow } from "@/shared/lib/profile/defaultUser";

type Props = {
  nick: string;
  email: string;
  flow: UserPasswordFlow;
  onStartChangePassword: () => void;
  onLogout?: () => void;
};

export default function UserSummary({ nick, email, flow, onStartChangePassword, onLogout }: Props) {
  return (
    <div className="profile-user-summary">
      <div className="profile-user-summary-row">
        <div className="profile-user-field">
          <div className="profile-label">Ник</div>
          <div className="profile-val">{nick}</div>
        </div>
        <div className="profile-user-field">
          <div className="profile-label">Почта</div>
          <div className="profile-val">{email}</div>
        </div>
      </div>
      {flow === "idle" ? (
        <div className="profile-user-text-actions">
          <button type="button" className="profile-user-change-text" onClick={onStartChangePassword}>
            Сменить пароль
          </button>
          {onLogout ? (
            <button type="button" className="profile-user-change-text profile-user-change-text--danger" onClick={onLogout}>
              Выйти
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

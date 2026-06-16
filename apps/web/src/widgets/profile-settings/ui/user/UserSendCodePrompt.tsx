"use client";

type Props = {
  email: string;
  onSend: () => void;
  onCancel: () => void;
};

export default function UserSendCodePrompt({ email, onSend, onCancel }: Props) {
  return (
    <div className="profile-user-send-code-prompt">
      <p className="profile-user-send-code-message">
        Код будет отправлен на вашу почту{" "}
        <span className="profile-user-send-code-email">{email}</span>
      </p>
      <div className="profile-user-text-actions">
        <button type="button" className="profile-user-change-text" onClick={onSend}>
          Отправить
        </button>
        <button
          type="button"
          className="profile-user-change-text profile-user-change-text--muted"
          onClick={onCancel}
        >
          Отменить
        </button>
      </div>
    </div>
  );
}

"use client";

function CloseIcon({ size = 16 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      aria-hidden
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <line x1="6.5" y1="6.5" x2="17.5" y2="17.5" />
      <line x1="17.5" y1="6.5" x2="6.5" y2="17.5" />
    </svg>
  );
}

type Props = {
  value: string;
  onChange: (value: string) => void;
  onDismiss: () => void;
};

export default function UserEmailCodeInput({ value, onChange, onDismiss }: Props) {
  return (
    <div className="telegram-code-input-field">
      <input
        className="profile-input telegram-code-input"
        type="text"
        inputMode="numeric"
        autoComplete="one-time-code"
        placeholder="Код из почты"
        maxLength={8}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <button
        type="button"
        className="telegram-code-input-dismiss"
        aria-label="Отменить смену пароля"
        onClick={onDismiss}
      >
        <CloseIcon size={14} />
      </button>
    </div>
  );
}

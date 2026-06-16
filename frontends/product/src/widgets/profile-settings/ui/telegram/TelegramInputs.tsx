"use client";

import { formatTelegramPhoneInput, TELEGRAM_PHONE_FORMATTED_MAX_LENGTH } from "@/shared/lib/format-telegram-phone";

export function TelegramPhoneInput({
  value,
  onChange,
  className = "",
}: {
  value: string;
  onChange: (value: string) => void;
  className?: string;
}) {
  return (
    <input
      className={`profile-input profile-input-explicit telegram-input ${className}`.trim()}
      type="tel"
      inputMode="tel"
      autoComplete="tel"
      maxLength={TELEGRAM_PHONE_FORMATTED_MAX_LENGTH}
      placeholder="+7 999 000-00-00"
      value={value}
      onChange={(e) => onChange(formatTelegramPhoneInput(e.target.value))}
    />
  );
}

export function TelegramCodeInput({
  value,
  onChange,
  onDismiss,
}: {
  value: string;
  onChange: (value: string) => void;
  onDismiss: () => void;
}) {
  return (
    <div className="telegram-code-input-field">
      <input
        className="profile-input telegram-code-input"
        placeholder="Код из Telegram"
        maxLength={8}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <button
        type="button"
        className="telegram-code-input-dismiss"
        aria-label="Отменить ввод кода"
        onClick={onDismiss}
      >
        <CloseIcon size={14} />
      </button>
    </div>
  );
}

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

function formatResendTimer(secondsLeft: number) {
  const minutes = Math.floor(secondsLeft / 60);
  const seconds = secondsLeft % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export function TelegramResendCode({
  secondsLeft,
  onResend,
}: {
  secondsLeft: number;
  onResend: () => void;
}) {
  if (secondsLeft > 0) {
    return (
      <p className="telegram-resend-code" aria-live="polite">
        Отправить код повторно ({formatResendTimer(secondsLeft)})
      </p>
    );
  }

  return (
    <button className="telegram-resend-code telegram-resend-code--ready" onClick={onResend} type="button">
      Отправить код повторно
    </button>
  );
}

"use client";

import { useState, type InputHTMLAttributes, type ReactNode } from "react";
import { PasswordToggleIcon } from "@/shared/ui/password-toggle";

/** Same classes as Telegram API / channel fields in profile. */
export const AUTH_FIELD_INPUT_CLASS = "profile-input profile-input-explicit telegram-input";

type AuthShellProps = {
  title: string;
  titleAction?: ReactNode;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
};

export function AuthShell({ title, titleAction, subtitle, children, footer }: AuthShellProps) {
  return (
    <div className="auth-page">
      <div className="profile-page auth-profile-scope">
        <div className="profile-section auth-card">
          <div className="auth-page-header">
            <h1 className="profile-section-title auth-page-title">{title}</h1>
            {titleAction}
          </div>
          {subtitle ? <p className="auth-page-subtitle">{subtitle}</p> : null}
          {children}
          {footer}
        </div>
      </div>
    </div>
  );
}

type AuthFieldProps = {
  label: string;
  hint?: ReactNode;
  error?: boolean;
  children: ReactNode;
};

export function AuthField({ label, hint, error, children }: AuthFieldProps) {
  return (
    <div className="profile-row auth-field">
      <div className="profile-label">{label}</div>
      {children}
      {hint ? (
        <span className={`auth-field-hint${error ? " auth-field-hint--error" : ""}`}>{hint}</span>
      ) : null}
    </div>
  );
}

export function AuthInput({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  const inputClass = [AUTH_FIELD_INPUT_CLASS, className].filter(Boolean).join(" ");
  return <input {...props} className={inputClass} />;
}

type AuthPasswordInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & {
  toggleLabel?: string;
};

export function AuthPasswordInput({ toggleLabel = "пароль", className, ...props }: AuthPasswordInputProps) {
  const [visible, setVisible] = useState(false);
  const inputClass = [AUTH_FIELD_INPUT_CLASS, "telegram-input-with-toggle", className]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="telegram-input-wrap">
      <input {...props} type={visible ? "text" : "password"} className={inputClass} />
      <button
        type="button"
        className="profile-api-key-toggle"
        aria-label={visible ? `Скрыть ${toggleLabel}` : `Показать ${toggleLabel}`}
        title={visible ? `Скрыть ${toggleLabel}` : `Показать ${toggleLabel}`}
        onClick={() => setVisible((value) => !value)}
      >
        <PasswordToggleIcon hidden={!visible} />
      </button>
    </div>
  );
}

export function AuthPrimaryActions({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`profile-action-buttons profile-action-buttons--ai auth-form-actions${className ? ` ${className}` : ""}`}
    >
      {children}
    </div>
  );
}

export function AuthSecondaryLink({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      className="telegram-resend-code telegram-resend-code--ready"
      onClick={onClick}
    >
      {children}
    </button>
  );
}

export function AuthHeaderLink({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button type="button" className="auth-header-link telegram-resend-code--ready" onClick={onClick}>
      {children}
    </button>
  );
}

export function AuthDemoHint({ children }: { children: ReactNode }) {
  return <p className="auth-demo-hint">{children}</p>;
}

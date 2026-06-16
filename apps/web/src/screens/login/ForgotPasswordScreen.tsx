"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { forgotPasswordReset, forgotPasswordSendCode } from "@/entities/auth";
import { DEMO_EMAIL, DEMO_EMAIL_CODE } from "@/shared/lib/auth/constants";
import { checkPasswordStrength, PASSWORD_REQUIREMENTS_HINT } from "@/shared/lib/check-password-strength";
import { routes } from "@/shared/lib/routes";
import { getApiErrorMessage } from "@/shared/api/getApiErrorMessage";
import { showToast } from "@/shared/ui/toast";
import {
  AuthDemoHint,
  AuthField,
  AuthHeaderLink,
  AuthInput,
  AuthPasswordInput,
  AuthPrimaryActions,
  AuthShell,
} from "@/screens/_ui/auth-shell";

type Step = "email" | "code" | "password";

type Props = {
  variant?: "page" | "overlay";
  onOpenLogin?: () => void;
};

export function ForgotPasswordScreen({ variant = "page", onOpenLogin }: Props = {}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState(searchParams.get("email") ?? DEMO_EMAIL);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const passwordStrength = checkPasswordStrength(password);
  const canReset =
    password.trim().length > 0 &&
    password.trim() === passwordConfirm.trim() &&
    !passwordStrength.isWeak;

  const handleSendCode = async () => {
    if (submitting) return;
    setSubmitting(true);
    try {
      await forgotPasswordSendCode({ email: email.trim() });
      setStep("code");
      showToast({ message: "Код отправлен (демо: 000000)", variant: "info" });
    } catch (error) {
      showToast({
        message: getApiErrorMessage(error, "Не удалось отправить код"),
        variant: "error",
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleConfirmCode = () => {
    if (!code.trim()) return;
    setStep("password");
  };

  const handleReset = async () => {
    if (!canReset || submitting) return;
    setSubmitting(true);
    try {
      await forgotPasswordReset({
        email: email.trim(),
        code: code.trim(),
        password: password.trim(),
      });
      showToast({ message: "Пароль обновлён. Войдите с новым паролем.", variant: "info" });
      if (onOpenLogin) onOpenLogin();
      else router.replace(routes.login());
    } catch (error) {
      showToast({
        message: getApiErrorMessage(error, "Не удалось сменить пароль"),
        variant: "error",
      });
    } finally {
      setSubmitting(false);
    }
  };

  const openLogin = () => {
    if (onOpenLogin) onOpenLogin();
    else router.push(routes.login());
  };

  return (
    <AuthShell
      title="Восстановление пароля"
      titleAction={<AuthHeaderLink onClick={openLogin}>Вход</AuthHeaderLink>}
    >
      <AuthDemoHint>Демо: код подтверждения — {DEMO_EMAIL_CODE}</AuthDemoHint>

      {step === "email" ? (
        <div className="auth-form">
          <AuthField label="Email">
            <AuthInput type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </AuthField>
          <AuthPrimaryActions>
            <button type="button" className="btn btn-primary" onClick={handleSendCode} disabled={submitting}>
              Отправить код
            </button>
          </AuthPrimaryActions>
        </div>
      ) : null}

      {step === "code" ? (
        <div className="auth-form">
          <AuthField label="Код из почты">
            <AuthInput inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} />
          </AuthField>
          <AuthPrimaryActions>
            <button type="button" className="btn btn-primary" onClick={handleConfirmCode}>
              Подтвердить код
            </button>
          </AuthPrimaryActions>
        </div>
      ) : null}

      {step === "password" ? (
        <div className="auth-form">
          <AuthField
            label="Новый пароль"
            hint={passwordStrength.message ?? PASSWORD_REQUIREMENTS_HINT}
            error={!!passwordStrength.message}
          >
            <AuthPasswordInput value={password} onChange={(e) => setPassword(e.target.value)} toggleLabel="новый пароль" />
          </AuthField>
          <AuthField label="Повторите пароль">
            <AuthPasswordInput
              value={passwordConfirm}
              onChange={(e) => setPasswordConfirm(e.target.value)}
              toggleLabel="повтор пароля"
            />
          </AuthField>
          <AuthPrimaryActions>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleReset}
              disabled={!canReset || submitting}
            >
              Сохранить пароль
            </button>
          </AuthPrimaryActions>
        </div>
      ) : null}
    </AuthShell>
  );
}

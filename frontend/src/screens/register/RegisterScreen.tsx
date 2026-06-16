"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { registerSendCode, registerVerify } from "@/entities/auth";
import { useAuth } from "@/app/providers/AuthProvider";
import { DEMO_EMAIL_CODE } from "@/shared/lib/auth/constants";
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

type Step = "email" | "password" | "code";

type Props = {
  variant?: "page" | "overlay";
  onOpenLogin?: () => void;
};

export function RegisterScreen({ variant = "page", onOpenLogin }: Props = {}) {
  const router = useRouter();
  const { setSession } = useAuth();
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const passwordStrength = checkPasswordStrength(password);
  const canSendCode =
    password.trim().length > 0 &&
    password.trim() === passwordConfirm.trim() &&
    !passwordStrength.isWeak;
  const mailRuHint = email.includes("@") && !email.toLowerCase().endsWith("@mail.ru");

  const handleEmailNext = () => {
    if (!email.trim()) {
      showToast({ message: "Укажите email", variant: "error" });
      return;
    }
    setStep("password");
  };

  const handleSendCode = async () => {
    if (passwordStrength.isWeak || !password.trim()) {
      showToast({ message: passwordStrength.message ?? PASSWORD_REQUIREMENTS_HINT, variant: "error" });
      return;
    }
    if (password.trim() !== passwordConfirm.trim()) {
      showToast({ message: "Пароли не совпадают", variant: "error" });
      return;
    }
    if (submitting) return;
    setSubmitting(true);
    try {
      await registerSendCode({ email: email.trim(), password });
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

  const handleVerify = async () => {
    if (!code.trim() || submitting) return;
    setSubmitting(true);
    try {
      const session = await registerVerify({ email: email.trim(), code: code.trim() });
      setSession(session);
      router.replace(routes.home());
    } catch (error) {
      showToast({
        message: getApiErrorMessage(error, "Не удалось подтвердить регистрацию"),
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
      title="Регистрация"
      titleAction={<AuthHeaderLink onClick={openLogin}>Вход</AuthHeaderLink>}
    >
      <AuthDemoHint>Демо: код подтверждения — {DEMO_EMAIL_CODE}</AuthDemoHint>

      {step === "email" ? (
        <div className="auth-form">
          <AuthField
            label="Email"
            hint={mailRuHint ? "Рекомендуем почту @mail.ru для демо" : undefined}
          >
            <AuthInput
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </AuthField>
          <AuthPrimaryActions>
            <button type="button" className="btn btn-primary" onClick={handleEmailNext}>
              Далее
            </button>
          </AuthPrimaryActions>
        </div>
      ) : null}

      {step === "password" ? (
        <div className="auth-form">
          <AuthField
            label="Пароль"
            hint={passwordStrength.message ?? PASSWORD_REQUIREMENTS_HINT}
            error={!!passwordStrength.message}
          >
            <AuthPasswordInput
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </AuthField>
          <AuthField label="Повторите пароль">
            <AuthPasswordInput
              autoComplete="new-password"
              value={passwordConfirm}
              onChange={(e) => setPasswordConfirm(e.target.value)}
              toggleLabel="повтор пароля"
            />
          </AuthField>
          <AuthPrimaryActions>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleSendCode}
              disabled={!canSendCode || submitting}
            >
              Отправить код на почту
            </button>
          </AuthPrimaryActions>
        </div>
      ) : null}

      {step === "code" ? (
        <div className="auth-form">
          <AuthField label="Код из почты">
            <AuthInput
              inputMode="numeric"
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </AuthField>
          <AuthPrimaryActions>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleVerify}
              disabled={submitting}
            >
              {submitting ? "Создаём аккаунт…" : "Подтвердить"}
            </button>
          </AuthPrimaryActions>
        </div>
      ) : null}
    </AuthShell>
  );
}

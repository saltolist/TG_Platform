"use client";

import { Suspense, useEffect, useState } from "react";

import { useAuth } from "@/app/providers/AuthProvider";
import { LoginScreen } from "@/screens/login/LoginScreen";
import { RegisterScreen } from "@/screens/register/RegisterScreen";
import { ForgotPasswordScreen } from "@/screens/login/ForgotPasswordScreen";

type AuthOverlayView = "login" | "register" | "forgot";

export function AuthOverlay() {
  const { authOverlayOpen, closeAuthOverlay } = useAuth();
  const [view, setView] = useState<AuthOverlayView>("login");

  useEffect(() => {
    if (authOverlayOpen) setView("login");
  }, [authOverlayOpen]);

  if (!authOverlayOpen) return null;

  return (
    <div className="auth-overlay" role="dialog" aria-modal="true" aria-label="Вход и регистрация">
      <button
        type="button"
        className="auth-overlay-close"
        aria-label="Закрыть"
        onClick={closeAuthOverlay}
      >
        <svg className="auth-overlay-close-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </button>
      <div className="auth-overlay-panel">
        {view === "login" ? (
          <LoginScreen
            variant="overlay"
            onOpenRegister={() => setView("register")}
            onOpenForgot={() => setView("forgot")}
          />
        ) : null}
        {view === "register" ? (
          <RegisterScreen variant="overlay" onOpenLogin={() => setView("login")} />
        ) : null}
        {view === "forgot" ? (
          <Suspense fallback={null}>
            <ForgotPasswordScreen variant="overlay" onOpenLogin={() => setView("login")} />
          </Suspense>
        ) : null}
      </div>
    </div>
  );
}

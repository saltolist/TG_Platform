"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { checkPasswordStrength } from "@/shared/lib/check-password-strength";
import { DEFAULT_USER, type UserPasswordFlow } from "@/shared/lib/profile/defaultUser";

const RESEND_COOLDOWN_SECONDS = 60;

export function useUserBlock() {
  const [flow, setFlow] = useState<UserPasswordFlow>("idle");
  const [emailCode, setEmailCode] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [passwordConfirmVisible, setPasswordConfirmVisible] = useState(false);
  const [resendCooldownSec, setResendCooldownSec] = useState(0);
  const resendIntervalRef = useRef<number | null>(null);

  const clearResendCooldown = useCallback(() => {
    if (resendIntervalRef.current !== null) {
      window.clearInterval(resendIntervalRef.current);
      resendIntervalRef.current = null;
    }
    setResendCooldownSec(0);
  }, []);

  const beginResendCooldown = useCallback(() => {
    if (resendIntervalRef.current !== null) {
      window.clearInterval(resendIntervalRef.current);
      resendIntervalRef.current = null;
    }
    setResendCooldownSec(RESEND_COOLDOWN_SECONDS);
    resendIntervalRef.current = window.setInterval(() => {
      setResendCooldownSec((prev) => {
        if (prev <= 1) {
          if (resendIntervalRef.current !== null) {
            window.clearInterval(resendIntervalRef.current);
            resendIntervalRef.current = null;
          }
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }, []);

  useEffect(() => {
    if (flow === "code") beginResendCooldown();
    else clearResendCooldown();
    return () => clearResendCooldown();
  }, [flow, beginResendCooldown, clearResendCooldown]);

  useEffect(() => {
    return () => clearResendCooldown();
  }, [clearResendCooldown]);

  const resetFlow = () => {
    setFlow("idle");
    setEmailCode("");
    setPassword("");
    setPasswordConfirm("");
    setPasswordVisible(false);
    setPasswordConfirmVisible(false);
  };

  const startChangePassword = () => {
    setFlow("confirm-send");
    setEmailCode("");
    setPassword("");
    setPasswordConfirm("");
  };

  const sendEmailCode = () => {
    setFlow("code");
    setEmailCode("");
    setPassword("");
    setPasswordConfirm("");
  };

  const resendEmailCode = () => {
    if (resendCooldownSec > 0 || flow !== "code") return;
    beginResendCooldown();
  };

  const confirmEmailCode = () => {
    if (!emailCode.trim()) return;
    setFlow("password");
    setPassword("");
    setPasswordConfirm("");
  };

  const confirmNewPassword = () => {
    const next = password.trim();
    const repeat = passwordConfirm.trim();
    if (!next || next !== repeat || checkPasswordStrength(next).isWeak) return;
    resetFlow();
  };

  const passwordStrength = checkPasswordStrength(password);
  const passwordsMismatch =
    flow === "password" &&
    passwordConfirm.length > 0 &&
    password.trim() !== passwordConfirm.trim();
  const canConfirmPassword =
    password.trim().length > 0 &&
    passwordConfirm.trim().length > 0 &&
    password.trim() === passwordConfirm.trim() &&
    !passwordStrength.isWeak;

  return {
    defaultUser: DEFAULT_USER,
    flow,
    emailCode,
    setEmailCode,
    password,
    setPassword,
    passwordConfirm,
    setPasswordConfirm,
    passwordVisible,
    passwordConfirmVisible,
    resendCooldownSec,
    passwordStrength,
    passwordsMismatch,
    canConfirmPassword,
    startChangePassword,
    resetFlow,
    sendEmailCode,
    resendEmailCode,
    confirmEmailCode,
    confirmNewPassword,
    togglePasswordVisible: () => setPasswordVisible((v) => !v),
    togglePasswordConfirmVisible: () => setPasswordConfirmVisible((v) => !v),
  };
}

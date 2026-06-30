"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useUpdateTelegramProfile } from "@/entities/channel";
import { useRepositories } from "@/app/providers/RepositoryProvider";
import { getApiErrorMessage } from "@/shared/api/getApiErrorMessage";
import { DEMO_CHANNEL_TITLE } from "@/shared/lib/auth/constants";
import { isDemoChannelHandle } from "@/shared/lib/channel/isDemoChannelHandle";
import { refreshPostsAfterChannelImport } from "@/widgets/profile-settings/lib/syncProfileDraftAfterChannelImport";
import { isTelegramPhoneComplete } from "@/shared/lib/format-telegram-phone";
import {
  getTelegramStatusLabel,
  normalizeTelegramValue,
  parseTelegramSnapshot,
  telegramConfigSnapshot,
} from "@/shared/lib/profile/telegramSnapshot";
import {
  domainActions,
  selectTelegramProfileConfig,
  selectTelegramSettingsSavedSnapshot,
  useDomainActions,
  useDomainDispatch,
  useDomainSelector,
  useUi,
} from "@/app/model/store";
import type { TelegramProfileConfig } from "@/shared/types";
import { confirmDialog } from "@/shared/ui/dialog";
import { reportMutationError, showToast } from "@/shared/ui/toast";

const RESEND_COOLDOWN_SECONDS = 60;
const IMPORT_POLL_INTERVAL_MS = 3000;

export function useTelegramBlock() {
  const cfg = useDomainSelector(selectTelegramProfileConfig);
  const telegramSettingsSavedSnapshot = useDomainSelector(selectTelegramSettingsSavedSnapshot);
  const dispatch = useDomainDispatch();
  const { applyPatch } = useDomainActions();
  const { setDirty } = useUi();
  const updateTelegramProfile = useUpdateTelegramProfile();
  const { profile } = useRepositories();
  const queryClient = useQueryClient();
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [savingCredentials, setSavingCredentials] = useState(false);
  const [connectingBot, setConnectingBot] = useState(false);
  const [sendingCode, setSendingCode] = useState(false);
  const [verifyingCode, setVerifyingCode] = useState(false);
  const [verifyingPassword, setVerifyingPassword] = useState(false);
  const [resettingAuth, setResettingAuth] = useState(false);
  const [connectingChannel, setConnectingChannel] = useState(false);
  const [resendCooldownSec, setResendCooldownSec] = useState(0);
  const [credentialsFlashNonce, setCredentialsFlashNonce] = useState(0);
  const syncTimerRef = useRef<number | null>(null);
  const resendIntervalRef = useRef<number | null>(null);
  const importIntervalRef = useRef<number | null>(null);
  const authBeforeCodeSentRef = useRef<Partial<TelegramProfileConfig> | null>(null);

  const update = (patch: Partial<TelegramProfileConfig>) =>
    dispatch(domainActions.updateTelegramConfig({ ...cfg, ...patch }));

  const currentSnap = telegramConfigSnapshot(cfg);
  const dirty = currentSnap !== telegramSettingsSavedSnapshot;

  useEffect(() => {
    setDirty("profile-telegram", dirty);
  }, [dirty, setDirty]);

  const clearResendCooldown = useCallback(() => {
    if (resendIntervalRef.current !== null) {
      window.clearInterval(resendIntervalRef.current);
      resendIntervalRef.current = null;
    }
    setResendCooldownSec(0);
  }, []);

  const clearImportPolling = useCallback(() => {
    if (importIntervalRef.current !== null) {
      window.clearInterval(importIntervalRef.current);
      importIntervalRef.current = null;
    }
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
    if (cfg.authStatus === "code-sent") beginResendCooldown();
    else clearResendCooldown();
    return () => clearResendCooldown();
  }, [cfg.authStatus, beginResendCooldown, clearResendCooldown]);

  useEffect(() => {
    return () => {
      setDirty("profile-telegram", false);
      if (syncTimerRef.current !== null) window.clearTimeout(syncTimerRef.current);
      clearResendCooldown();
      clearImportPolling();
    };
  }, [setDirty, clearResendCooldown, clearImportPolling]);

  useEffect(() => {
    if (cfg.importStatus !== "importing") return;

    const poll = async () => {
      try {
        const latest = await profile.getTelegram();
        dispatch(domainActions.updateTelegramConfig(latest));
        if (latest.importStatus !== "importing") {
          clearImportPolling();
          applyPatch({ telegramSettingsSavedSnapshot: telegramConfigSnapshot(latest) });
          if (latest.importStatus === "done") {
            showToast({
              message: `Импортировано ${latest.importedPosts} постов`,
              variant: "info",
            });
            await refreshPostsAfterChannelImport(queryClient);
          } else if (latest.importStatus === "error") {
            showToast({
              message: latest.importError || "Не удалось импортировать историю постов",
              variant: "error",
            });
          }
        }
      } catch {
        // Transient errors — keep polling until import finishes or user leaves.
      }
    };

    importIntervalRef.current = window.setInterval(() => {
      void poll();
    }, IMPORT_POLL_INTERVAL_MS);

    return clearImportPolling;
  }, [cfg.importStatus, profile, dispatch, applyPatch, queryClient, clearImportPolling]);

  const importing = cfg.importStatus === "importing";
  const status = getTelegramStatusLabel(cfg, syncing, importing);
  const isConnected = cfg.authStatus === "connected" && cfg.channelStatus === "connected";
  const isAuthorized = cfg.authStatus === "authorized" || cfg.authStatus === "connected";
  const codeHidden = cfg.authStatus !== "code-sent";
  const awaitingPassword = cfg.authStatus === "code-sent" && cfg.authStep === "password";
  const savedSnapshot = parseTelegramSnapshot(telegramSettingsSavedSnapshot);
  const apiIdChangedFromSaved = normalizeTelegramValue(cfg.apiId) !== normalizeTelegramValue(savedSnapshot.apiId);
  const apiHashChangedFromSaved = normalizeTelegramValue(cfg.apiHash) !== normalizeTelegramValue(savedSnapshot.apiHash);
  const apiChangedFromSaved = apiIdChangedFromSaved || apiHashChangedFromSaved;
  const phoneChangedFromSaved = normalizeTelegramValue(cfg.phone) !== normalizeTelegramValue(savedSnapshot.phone);
  const channelChangedFromSaved = normalizeTelegramValue(cfg.channel) !== normalizeTelegramValue(savedSnapshot.channel);
  const phoneIncomplete = !isTelegramPhoneComplete(cfg.phone);
  const sendCodeDisabled =
    phoneIncomplete || (isAuthorized && !phoneChangedFromSaved) || sendingCode;
  const connectChannelDisabled =
    (isConnected && !channelChangedFromSaved) || importing;
  const isBotConnected = cfg.botStatus === "connected";
  const botTokenTrimmed = cfg.botApiToken.trim();
  const botTokenChangedFromSaved =
    normalizeTelegramValue(cfg.botApiToken) !== normalizeTelegramValue(savedSnapshot.botApiToken || "");
  const addBotDisabled = !botTokenTrimmed || (isBotConnected && !botTokenChangedFromSaved);
  const apiIdMissing = !normalizeTelegramValue(cfg.apiId);
  const apiHashMissing = !normalizeTelegramValue(cfg.apiHash);

  const flashCredentialsMarks = () => setCredentialsFlashNonce((n) => n + 1);

  const rejectSendCodeValidation = () => {
    if (apiIdMissing || apiHashMissing) {
      flashCredentialsMarks();
      showToast({ message: "Заполните поля api_id и api_hash", variant: "error" });
      return true;
    }
    if (phoneIncomplete) {
      showToast({ message: "Заполните номер телефона", variant: "error" });
      return true;
    }
    return false;
  };

  const sendCode = async () => {
    setSendingCode(true);
    try {
      const saved = await profile.sendTelegramCode(cfg.phone);
      update(saved);
      applyPatch({ telegramSettingsSavedSnapshot: telegramConfigSnapshot(saved) });
      setCode("");
      setPassword("");
    } catch (error) {
      showToast({
        message: getApiErrorMessage(error, "Не удалось отправить код"),
        variant: "error",
      });
    } finally {
      setSendingCode(false);
    }
  };

  const startAuth = async () => {
    if (sendCodeDisabled) return;
    if (rejectSendCodeValidation()) return;
    const reauthorizing = isAuthorized && phoneChangedFromSaved;
    if (reauthorizing) {
      const ok = await confirmDialog({
        message:
          "При переподключении телефона данные прошлого аккаунта и подключенного канала будут недоступны, пока вы не подключите их снова.",
        confirmLabel: "Продолжить",
        destructive: true,
      });
      if (!ok) return;
      setSyncing(false);
      if (syncTimerRef.current !== null) {
        window.clearTimeout(syncTimerRef.current);
        syncTimerRef.current = null;
      }
    }
    authBeforeCodeSentRef.current = {
      authStatus: cfg.authStatus,
      authStep: cfg.authStep,
      channelStatus: cfg.channelStatus,
      channelTitle: cfg.channelTitle,
      lastSync: cfg.lastSync,
      importedPosts: cfg.importedPosts,
    };
    if (reauthorizing) {
      update({
        channelStatus: cfg.channelStatus === "connected" ? "pending" : cfg.channelStatus,
        channelTitle: "",
        lastSync: "—",
        importedPosts: 0,
      });
    }
    await sendCode();
  };

  const resendCode = async () => {
    if (resendCooldownSec > 0 || sendCodeDisabled || cfg.authStatus !== "code-sent") return;
    if (rejectSendCodeValidation()) return;
    await sendCode();
    beginResendCooldown();
  };

  const cancelCodeEntry = async () => {
    const prev = authBeforeCodeSentRef.current;
    authBeforeCodeSentRef.current = null;
    const patch: Partial<TelegramProfileConfig> =
      prev ?? { authStatus: "idle", authStep: "credentials" };
    const merged = { ...cfg, ...patch };
    const previousCfg = cfg;
    setCode("");
    setPassword("");
    update(patch);
    try {
      const saved = await updateTelegramProfile.mutateAsync(merged);
      update(saved);
      applyPatch({ telegramSettingsSavedSnapshot: telegramConfigSnapshot(saved) });
    } catch (error) {
      update(previousCfg);
      reportMutationError(error, "Не удалось отменить ввод кода");
    }
  };

  /** After a verify error the backend may have already changed state server-side
   * (e.g. an expired code resets authStatus to "idle") — resync to be sure. */
  const resyncAfterVerifyError = async () => {
    try {
      const fresh = await profile.getTelegram();
      update(fresh);
    } catch {
      // Best-effort only — keep whatever is currently shown.
    }
  };

  const confirmCode = async () => {
    if (!code.trim() || verifyingCode) return;
    setVerifyingCode(true);
    try {
      const saved = await profile.verifyTelegramCode(code);
      update(saved);
      applyPatch({ telegramSettingsSavedSnapshot: telegramConfigSnapshot(saved) });
      if (saved.authStep === "password") {
        setPassword("");
      } else {
        authBeforeCodeSentRef.current = null;
        setCode("");
      }
    } catch (error) {
      showToast({
        message: getApiErrorMessage(error, "Не удалось подтвердить код"),
        variant: "error",
      });
      await resyncAfterVerifyError();
    } finally {
      setVerifyingCode(false);
    }
  };

  const confirmPassword = async () => {
    if (!password.trim() || verifyingPassword) return;
    setVerifyingPassword(true);
    try {
      const saved = await profile.verifyTelegram2fa(password);
      update(saved);
      applyPatch({ telegramSettingsSavedSnapshot: telegramConfigSnapshot(saved) });
      authBeforeCodeSentRef.current = null;
      setCode("");
      setPassword("");
    } catch (error) {
      showToast({
        message: getApiErrorMessage(error, "Не удалось подтвердить пароль"),
        variant: "error",
      });
      await resyncAfterVerifyError();
    } finally {
      setVerifyingPassword(false);
    }
  };

  /** @demochannel is a trial feed available to every account type — it never
   * touches real Telegram, so it keeps the original "instant success" local
   * simulation (the backend still does the actual demo-post import on PUT). */
  const connectDemoChannel = async () => {
    if (syncTimerRef.current !== null) window.clearTimeout(syncTimerRef.current);
    const next: Partial<TelegramProfileConfig> = {
      authStatus: "connected",
      authStep: "connected",
      channelStatus: "connected",
      channelTitle: DEMO_CHANNEL_TITLE,
      lastSync: new Date().toISOString(),
      importStatus: "done",
      importError: "",
    };
    const merged = { ...cfg, ...next };
    update(next);
    setSyncing(true);
    try {
      const saved = await updateTelegramProfile.mutateAsync(merged);
      update(saved);
      applyPatch({ telegramSettingsSavedSnapshot: telegramConfigSnapshot(saved) });
      if (saved.channelStatus === "connected" && isDemoChannelHandle(saved.channel)) {
        await refreshPostsAfterChannelImport(queryClient);
      }
    } catch {
      update(cfg);
      showToast({ message: "Не удалось подключить канал", variant: "error" });
      setSyncing(false);
      return;
    }
    syncTimerRef.current = window.setTimeout(() => {
      setSyncing(false);
      syncTimerRef.current = null;
    }, 1800);
  };

  /** Real channel: verified via Telethon on the backend (existence + admin rights). */
  const connectRealChannel = async () => {
    setConnectingChannel(true);
    try {
      const saved = await profile.connectTelegramChannel(cfg.channel);
      update(saved);
      applyPatch({ telegramSettingsSavedSnapshot: telegramConfigSnapshot(saved) });
    } catch (error) {
      showToast({
        message: getApiErrorMessage(error, "Не удалось подключить канал"),
        variant: "error",
      });
    } finally {
      setConnectingChannel(false);
    }
  };

  const connectChannel = async () => {
    if (connectChannelDisabled || connectingChannel) return;
    if (isConnected && channelChangedFromSaved) {
      const ok = await confirmDialog({
        message:
          "При подключении другого канала данные прошлого канала будут недоступны, пока вы не подключите его снова.",
        confirmLabel: "Продолжить",
        destructive: true,
      });
      if (!ok) return;
    }
    if (isDemoChannelHandle(cfg.channel)) {
      await connectDemoChannel();
    } else {
      await connectRealChannel();
    }
  };

  const connectBot = async () => {
    if (addBotDisabled || connectingBot) return;
    const tokenHint = botTokenTrimmed.slice(0, 8);
    const next: Partial<TelegramProfileConfig> = {
      botStatus: "connected",
      botUsername: `@omni_bot_${tokenHint}`,
      botLastActivity: new Date().toISOString(),
      botMessageCount: 0,
    };
    const merged = { ...cfg, ...next };
    const previousSnapshot = telegramSettingsSavedSnapshot;
    update(next);
    setConnectingBot(true);
    try {
      const saved = await updateTelegramProfile.mutateAsync(merged);
      update(saved);
      applyPatch({ telegramSettingsSavedSnapshot: telegramConfigSnapshot(saved) });
    } catch (error) {
      update(cfg);
      applyPatch({ telegramSettingsSavedSnapshot: previousSnapshot });
      reportMutationError(error, "Не удалось сохранить токен бота");
    } finally {
      setConnectingBot(false);
    }
  };

  const reset = async () => {
    if (resettingAuth) return;
    if (syncTimerRef.current !== null) {
      window.clearTimeout(syncTimerRef.current);
      syncTimerRef.current = null;
    }
    clearImportPolling();
    setSyncing(false);
    setCredentialsFlashNonce(0);
    setCode("");
    setPassword("");
    authBeforeCodeSentRef.current = null;
    const previousCfg = cfg;
    setResettingAuth(true);
    try {
      const authReset = await profile.resetTelegramAuth();
      const merged: TelegramProfileConfig = {
        ...authReset,
        channelStatus: "idle",
        lastSync: "—",
        importedPosts: 0,
        importStatus: "idle",
        importError: "",
        botApiToken: "",
        botStatus: "idle",
        botUsername: "",
        botLastActivity: "—",
        botMessageCount: 0,
      };
      const saved = await updateTelegramProfile.mutateAsync(merged);
      update(saved);
      applyPatch({ telegramSettingsSavedSnapshot: telegramConfigSnapshot(saved) });
    } catch (error) {
      update(previousCfg);
      reportMutationError(error, "Не удалось сбросить настройки Telegram");
    } finally {
      setResettingAuth(false);
    }
  };

  const saveApiCredentials = async () => {
    if (!apiChangedFromSaved || savingCredentials) return;
    const previousSnapshot = telegramSettingsSavedSnapshot;
    applyPatch({ telegramSettingsSavedSnapshot: currentSnap });
    setSavingCredentials(true);
    try {
      const saved = await updateTelegramProfile.mutateAsync(cfg);
      const savedSnap = telegramConfigSnapshot(saved);
      update(saved);
      applyPatch({ telegramSettingsSavedSnapshot: savedSnap });
      showToast({ message: "API-данные Telegram сохранены", variant: "info" });
    } catch (error) {
      applyPatch({ telegramSettingsSavedSnapshot: previousSnapshot });
      reportMutationError(error, "Не удалось сохранить API-данные");
    } finally {
      setSavingCredentials(false);
    }
  };

  const cancelApiCredentials = () => {
    if (!apiChangedFromSaved) return;
    update({ apiId: savedSnapshot.apiId, apiHash: savedSnapshot.apiHash });
  };
  return {
    cfg,
    update,
    status,
    isConnected,
    isAuthorized,
    codeHidden,
    awaitingPassword,
    syncing,
    importing,
    code,
    setCode,
    password,
    setPassword,
    savingCredentials,
    connectingBot,
    sendingCode,
    verifyingCode,
    verifyingPassword,
    resettingAuth,
    connectingChannel,
    resendCooldownSec,
    apiChangedFromSaved,
    apiIdMissing,
    apiHashMissing,
    credentialsFlashNonce,
    sendCodeDisabled,
    connectChannelDisabled,
    isBotConnected,
    addBotDisabled,
    startAuth,
    resendCode,
    cancelCodeEntry,
    confirmCode,
    confirmPassword,
    connectChannel,
    connectBot,
    reset,
    saveApiCredentials,
    cancelApiCredentials,
  };
}

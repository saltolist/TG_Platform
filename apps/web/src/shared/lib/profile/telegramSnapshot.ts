import type { TelegramProfileConfig } from "@/shared/types";

export function telegramConfigSnapshot(cfg: TelegramProfileConfig) {
  return JSON.stringify({
    apiId: cfg.apiId || "",
    apiHash: cfg.apiHash || "",
    phone: cfg.phone || "",
    sessionName: cfg.sessionName || "",
    channel: cfg.channel || "",
    botApiToken: cfg.botApiToken || "",
    botStatus: cfg.botStatus,
  });
}

export function parseTelegramSnapshot(snapshotJson: string): Pick<
  TelegramProfileConfig,
  "apiId" | "apiHash" | "phone" | "sessionName" | "channel" | "botApiToken"
> {
  try {
    const saved = JSON.parse(snapshotJson) as Partial<TelegramProfileConfig>;
    return {
      apiId: saved.apiId || "",
      apiHash: saved.apiHash || "",
      phone: saved.phone || "",
      sessionName: saved.sessionName || "",
      channel: saved.channel || "",
      botApiToken: saved.botApiToken || "",
    };
  } catch {
    return { apiId: "", apiHash: "", phone: "", sessionName: "", channel: "", botApiToken: "" };
  }
}

export function normalizeTelegramValue(value: string) {
  return value.trim().toLowerCase();
}

export function getTelegramStatusLabel(cfg: TelegramProfileConfig, syncing: boolean) {
  if (syncing) return { className: "syncing", text: "Синхронизация" };
  if (cfg.authStatus === "connected" && cfg.channelStatus === "connected") {
    return { className: "ok", text: "MTProto подключён" };
  }
  if (cfg.authStatus === "code-sent") return { className: "warn", text: "Ждёт код входа" };
  if (cfg.authStatus === "authorized") return { className: "warn", text: "Аккаунт авторизован" };
  return { className: "muted", text: "Не подключён" };
}

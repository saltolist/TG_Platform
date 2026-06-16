import { setupWorker, type SetupWorker } from "msw/browser";
import { BASE_PATH } from "@/shared/config/basePath";
import { handlers } from "./handlers";

let worker: SetupWorker | null = null;
let startPromise: Promise<void> | null = null;

function getWorker(): SetupWorker {
  if (!worker) worker = setupWorker(...handlers);
  return worker;
}

function resetMswRuntime(): void {
  worker = null;
  startPromise = null;
}

function resolveServiceWorkerConfig() {
  const base = BASE_PATH || "";
  return {
    url: `${base}/mockServiceWorker.js`,
    scope: base ? `${base}/` : "/",
  };
}

async function assertServiceWorkerScriptAvailable(url: string): Promise<void> {
  const response = await fetch(url, { method: "GET", cache: "no-store" });
  if (response.ok) return;

  throw new Error(
    `Файл mockServiceWorker.js не найден (${response.status}) по адресу ${url}. ` +
      `Проверьте NEXT_PUBLIC_BASE_PATH (${BASE_PATH || "не задан"}) и пересоберите проект.`,
  );
}

function assertSecureBrowserContext(): void {
  if (typeof window === "undefined") return;

  if (!("serviceWorker" in navigator)) {
    throw new Error("Service Worker недоступен в этом браузере.");
  }

  if (!window.isSecureContext) {
    throw new Error(
      "Демо-данные (MSW) работают только по localhost или HTTPS. " +
        "Откройте http://localhost:3020 на этом компьютере, а не по IP в локальной сети.",
    );
  }
}

async function unregisterStaleServiceWorkers(scope: string): Promise<void> {
  const registrations = await navigator.serviceWorker.getRegistrations();
  const targetScope = new URL(scope, window.location.origin).href;

  await Promise.all(
    registrations.map(async (registration) => {
      if (registration.scope === targetScope) return;
      await registration.unregister();
    }),
  );
}

async function bootMsw(): Promise<void> {
  assertSecureBrowserContext();

  const { url, scope } = resolveServiceWorkerConfig();
  await assertServiceWorkerScriptAvailable(url);
  await unregisterStaleServiceWorkers(scope);

  try {
    const activeWorker = getWorker();
    await activeWorker.start({
      onUnhandledRequest: process.env.NODE_ENV === "development" ? "warn" : "bypass",
      quiet: process.env.NODE_ENV === "production",
      serviceWorker: {
        url,
        options: { scope },
      },
    });
    await navigator.serviceWorker.ready;
  } catch (error) {
    resetMswRuntime();
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(
      `Не удалось зарегистрировать mockServiceWorker.js (${url}): ${reason}`,
      { cause: error },
    );
  }
}

/** Ensures MSW is running before API requests (also re-starts after Turbopack HMR). */
export async function ensureMswStarted(): Promise<void> {
  if (typeof window === "undefined") return;

  if (worker) {
    if (startPromise) await startPromise;
    return;
  }

  if (startPromise) {
    await startPromise;
    if (worker) return;
    startPromise = null;
  }

  startPromise = bootMsw().catch((error) => {
    resetMswRuntime();
    throw error;
  });
  await startPromise;
}

export async function startMsw(): Promise<void> {
  await ensureMswStarted();
}

if (process.env.NODE_ENV === "development" && typeof window !== "undefined") {
  const hot = (import.meta as ImportMeta & { hot?: { dispose(cb: () => void): void } }).hot;
  hot?.dispose(() => {
    void worker?.stop();
    resetMswRuntime();
  });
}

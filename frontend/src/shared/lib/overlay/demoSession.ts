import { DEMO_TENANT_PREFIX } from "@/shared/lib/auth/constants";

export const DEMO_SESSION_STORAGE_KEY = "tg-platform-demo-session";

export type DemoSession = {
  sessionId: string;
  key: string;
  createdAt: string;
};

function createSessionId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `demo-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function buildDemoTenantKey(sessionId: string): string {
  return `${DEMO_TENANT_PREFIX}${sessionId}`;
}

export function readDemoSession(): DemoSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(DEMO_SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as DemoSession;
    if (!parsed?.sessionId || parsed.key !== buildDemoTenantKey(parsed.sessionId)) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function writeDemoSession(session: DemoSession): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(DEMO_SESSION_STORAGE_KEY, JSON.stringify(session));
}

export function ensureDemoSession(): DemoSession {
  const existing = readDemoSession();
  if (existing) return existing;

  const sessionId = createSessionId();
  const session: DemoSession = {
    sessionId,
    key: buildDemoTenantKey(sessionId),
    createdAt: new Date().toISOString(),
  };
  writeDemoSession(session);
  return session;
}

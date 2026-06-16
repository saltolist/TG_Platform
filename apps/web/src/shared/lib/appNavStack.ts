import { routeSyncKey } from "@/shared/lib/routes";

const STACK_KEY = "tg-app-nav-stack";
const MAX_STACK = 40;

function getSessionStorage(): Storage | undefined {
  if (typeof globalThis === "undefined") return undefined;
  return globalThis.sessionStorage;
}

function readStack(): string[] {
  const storage = getSessionStorage();
  if (!storage) return [];
  try {
    const raw = storage.getItem(STACK_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? parsed.filter((item) => typeof item === "string") : [];
  } catch {
    return [];
  }
}

function writeStack(stack: string[]): void {
  const storage = getSessionStorage();
  if (!storage) return;
  storage.setItem(STACK_KEY, JSON.stringify(stack.slice(-MAX_STACK)));
}

/** Record in-app route changes (pathname + search). Detects browser back via stack rewind. */
export function recordAppNavigation(pathname: string, searchParams: URLSearchParams): void {
  const key = routeSyncKey(pathname, searchParams);
  const stack = readStack();
  if (stack.length >= 2 && stack[stack.length - 2] === key) {
    stack.pop();
    writeStack(stack);
    return;
  }
  if (stack[stack.length - 1] === key) return;
  stack.push(key);
  writeStack(stack);
}

export function canAppNavigateBack(pathname: string, searchParams: URLSearchParams): boolean {
  const key = routeSyncKey(pathname, searchParams);
  const stack = readStack();
  return stack.length >= 2 && stack[stack.length - 1] === key;
}

export function resetAppNavStackForTests(): void {
  getSessionStorage()?.removeItem(STACK_KEY);
}

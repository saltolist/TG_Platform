export type ToastOptions = {
  message: string;
  variant?: "error" | "info";
};

type ToastBridge = {
  show: (options: ToastOptions) => void;
};

let bridge: ToastBridge | null = null;

export function registerToastBridge(next: ToastBridge | null): void {
  bridge = next;
}

export function showToast(options: ToastOptions): void {
  if (bridge) {
    bridge.show(options);
    return;
  }
  if (typeof window !== "undefined") console.error("[toast]", options.message);
}

export function reportMutationError(error: unknown, fallback = "Не удалось выполнить действие"): void {
  const message = error instanceof Error && error.message ? error.message : fallback;
  showToast({ message, variant: "error" });
}

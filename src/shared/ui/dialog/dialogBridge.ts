export type ConfirmDialogOptions = {
  message: string;
  title?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
};

export type AlertDialogOptions = {
  message: string;
  title?: string;
  confirmLabel?: string;
};

type DialogBridge = {
  confirm: (options: ConfirmDialogOptions) => Promise<boolean>;
  alert: (options: AlertDialogOptions) => Promise<void>;
};

let bridge: DialogBridge | null = null;

export function registerDialogBridge(next: DialogBridge | null): void {
  bridge = next;
}

export function confirmDialog(options: ConfirmDialogOptions): Promise<boolean> {
  if (bridge) return bridge.confirm(options);
  if (typeof window !== "undefined") return Promise.resolve(window.confirm(options.message));
  return Promise.resolve(false);
}

export function alertDialog(options: AlertDialogOptions | string): Promise<void> {
  const payload = typeof options === "string" ? { message: options } : options;
  if (bridge) return bridge.alert(payload);
  if (typeof window !== "undefined") window.alert(payload.message);
  return Promise.resolve();
}

"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";

import { Button } from "@/shared/ui/button";
import {
  registerDialogBridge,
  type AlertDialogOptions,
  type ConfirmDialogOptions,
} from "./dialogBridge";

type ConfirmState = ConfirmDialogOptions & {
  resolve: (value: boolean) => void;
};

type AlertState = AlertDialogOptions & {
  resolve: () => void;
};

export function DialogProvider({ children }: { children: ReactNode }) {
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);
  const [alertState, setAlertState] = useState<AlertState | null>(null);

  const confirm = useCallback((options: ConfirmDialogOptions) => {
    return new Promise<boolean>((resolve) => {
      setConfirmState({ ...options, resolve });
    });
  }, []);

  const alert = useCallback((options: AlertDialogOptions) => {
    return new Promise<void>((resolve) => {
      setAlertState({ ...options, resolve });
    });
  }, []);

  useEffect(() => {
    registerDialogBridge({ confirm, alert });
    return () => registerDialogBridge(null);
  }, [alert, confirm]);

  const closeConfirm = (value: boolean) => {
    confirmState?.resolve(value);
    setConfirmState(null);
  };

  const closeAlert = () => {
    alertState?.resolve();
    setAlertState(null);
  };

  return (
    <>
      {children}
      {confirmState ? (
        <div
          className="app-dialog-backdrop"
          onClick={() => closeConfirm(false)}
          role="presentation"
        >
          <div
            className="app-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="app-dialog-title"
            aria-describedby="app-dialog-message"
            onClick={(e) => e.stopPropagation()}
          >
            {confirmState.title ? (
              <div className="app-dialog-title" id="app-dialog-title">
                {confirmState.title}
              </div>
            ) : null}
            <div className="app-dialog-message" id="app-dialog-message">
              {confirmState.message}
            </div>
            <div className="app-dialog-actions">
              <Button type="button" variant="outline" onClick={() => closeConfirm(false)}>
                {confirmState.cancelLabel ?? "Отмена"}
              </Button>
              <Button
                type="button"
                variant={confirmState.destructive ? "default" : "default"}
                className={confirmState.destructive ? "app-dialog-btn-danger" : undefined}
                onClick={() => closeConfirm(true)}
              >
                {confirmState.confirmLabel ?? "OK"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
      {alertState ? (
        <div className="app-dialog-backdrop" onClick={closeAlert} role="presentation">
          <div
            className="app-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="app-alert-dialog-title"
            aria-describedby="app-alert-dialog-message"
            onClick={(e) => e.stopPropagation()}
          >
            {alertState.title ? (
              <div className="app-dialog-title" id="app-alert-dialog-title">
                {alertState.title}
              </div>
            ) : null}
            <div className="app-dialog-message" id="app-alert-dialog-message">
              {alertState.message}
            </div>
            <div className="app-dialog-actions">
              <Button type="button" onClick={closeAlert}>
                {alertState.confirmLabel ?? "OK"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

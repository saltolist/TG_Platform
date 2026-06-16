"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { registerToastBridge, type ToastOptions } from "./toastBridge";

const TOAST_VISIBLE_MS = 2200;
const TOAST_FADE_MS = 450;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastOptions | null>(null);
  const [leaving, setLeaving] = useState(false);
  const visibleTimerRef = useRef<number | null>(null);
  const fadeTimerRef = useRef<number | null>(null);
  const clearTimers = () => {
    if (visibleTimerRef.current !== null) {
      window.clearTimeout(visibleTimerRef.current);
      visibleTimerRef.current = null;
    }
    if (fadeTimerRef.current !== null) {
      window.clearTimeout(fadeTimerRef.current);
      fadeTimerRef.current = null;
    }
  };

  const show = useCallback((options: ToastOptions) => {
    clearTimers();
    setLeaving(false);
    setToast(options);
    visibleTimerRef.current = window.setTimeout(() => {
      setLeaving(true);
      fadeTimerRef.current = window.setTimeout(() => {
        setToast(null);
        setLeaving(false);
        fadeTimerRef.current = null;
      }, TOAST_FADE_MS);
      visibleTimerRef.current = null;
    }, TOAST_VISIBLE_MS);
  }, []);

  useEffect(() => {
    registerToastBridge({ show });
    return () => {
      clearTimers();
      registerToastBridge(null);
    };
  }, [show]);

  return (
    <>
      {children}
      {toast ? (
        <div className="app-toast-host" role="status" aria-live="polite">
          <div
            className={`app-toast app-toast--${toast.variant ?? "info"}${leaving ? " app-toast--leaving" : ""}`}
          >
            {toast.message}
          </div>
        </div>
      ) : null}
    </>
  );
}

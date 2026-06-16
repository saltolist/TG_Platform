"use client";

import { useEffect, useState, type ReactNode } from "react";
import { startMsw } from "@/shared/api/msw/browser";
import { USE_MSW } from "@/shared/config/dataSource";
import { Button } from "@/shared/ui/button";
import { EmptyState } from "@/shared/ui/empty-state";

type MswProviderProps = {
  children: ReactNode;
};

type BootState = "ready" | "loading" | "error";

function formatMswBootError(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message;
  return "Не удалось запустить демо-данные (MSW). Проверьте mockServiceWorker.js и перезагрузите страницу.";
}

export function MswProvider({ children }: MswProviderProps) {
  const [bootState, setBootState] = useState<BootState>(USE_MSW ? "loading" : "ready");
  const [bootError, setBootError] = useState<string | null>(null);

  useEffect(() => {
    if (!USE_MSW) return;

    let cancelled = false;

    void startMsw()
      .then(() => {
        if (!cancelled) setBootState("ready");
      })
      .catch((error: unknown) => {
        console.error("[MSW] Failed to start mock worker", error);
        if (!cancelled) {
          setBootError(formatMswBootError(error));
          setBootState("error");
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  if (bootState === "loading") {
    return <div className="msw-boot-screen">Загрузка демо-данных…</div>;
  }

  if (bootState === "error") {
    return (
      <div className="msw-error-screen">
        <EmptyState
          message={bootError ?? formatMswBootError(null)}
          action={
            <Button type="button" onClick={() => window.location.reload()}>
              Перезагрузить
            </Button>
          }
        />
      </div>
    );
  }

  return children;
}

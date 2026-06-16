"use client";

import { useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { routes } from "@/shared/lib/routes";
import { EmptyState } from "@/shared/ui/empty-state";

export type ConnectChannelFeature =
  | "ленте"
  | "аналитике канала"
  | "чатам"
  | "заметкам"
  | "базе знаний канала"
  | "аналитике платформы";

export function connectChannelMessage(feature: ConnectChannelFeature): string {
  return `Подключите Telegram-канал в настройках для доступа к ${feature}.`;
}

type Props = {
  feature: ConnectChannelFeature;
  icon?: ReactNode;
  className?: string;
};

export function ConnectChannelEmptyState({ feature, icon = "📡", className }: Props) {
  const router = useRouter();

  return (
    <EmptyState
      icon={icon}
      message={connectChannelMessage(feature)}
      className={className}
      action={
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => router.push(routes.profile())}
        >
          Перейти в настройки
        </button>
      }
    />
  );
}

"use client";

import { useRouter } from "next/navigation";

import { useNavigationStore } from "@/app/model/store";
import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import { routes } from "@/shared/lib/routes";
import { FilterToolbar, FilterToolbarAction } from "@/widgets/filter-toolbar";

export function ChatsFilterRow() {
  const router = useRouter();
  const isMobile = useMobile760();
  const tab = useNavigationStore((s) => s.chatsTab);

  if (tab !== "global" && tab !== "all") return null;

  return (
    <FilterToolbar
      className="chats-filter-row"
      width="content"
      action={
        <FilterToolbarAction
          label="Новый чат"
          onClick={() => router.push(routes.home())}
          className={`chats-new-chat-btn${isMobile ? " filter-tab--dropdown" : ""}`}
          iconClassName="chats-new-chat-btn-icon"
        />
      }
    />
  );
}

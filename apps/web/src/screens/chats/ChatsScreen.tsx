"use client";

import { useMemo } from "react";

import { useNavigationStore } from "@/app/model/store";
import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import { useScreenBack } from "@/widgets/app-shell/model/useScreenBack";
import type { ChatsTab } from "@/shared/types";
import { ScreenShell } from "@/screens/_ui/screen-shell";
import { useChatsScreen } from "@/screens/chats/model/useChatsScreen";
import { ChatsFilterRow } from "@/screens/chats/ui/ChatsFilterRow";
import { ChatsList } from "@/screens/chats/ui/ChatsList";
import { PageHeader, PageHeaderSearchInput, PageHeaderSelect } from "@/widgets/page-header";

const TAB_OPTIONS = [
  { value: "all" as const, label: "Все" },
  { value: "global" as const, label: "Глобальные" },
  { value: "local" as const, label: "Локальные" },
];

export function ChatsScreen() {
  const onBack = useScreenBack();
  const isMobile = useMobile760();
  const { data, actions } = useChatsScreen();
  const tab = useNavigationStore((s) => s.chatsTab);
  const setChatsTab = useNavigationStore((s) => s.setChatsTab);
  const search = useNavigationStore((s) => s.chatsSearch);
  const setChatsSearch = useNavigationStore((s) => s.setChatsSearch);

  const chatsScopeSelectProps = useMemo(
    () => ({
      ariaLabel: "Область чатов",
      value: tab,
      options: TAB_OPTIONS,
      onChange: (v: string) => setChatsTab(v as ChatsTab),
    }),
    [tab, setChatsTab],
  );

  return (
    <ScreenShell
      bodyClassName="chats-page"
      header={
        <PageHeader
          title="Чаты"
          onBack={onBack}
          mobileSelect={isMobile ? <PageHeaderSelect {...chatsScopeSelectProps} /> : undefined}
          search={
            <div className="page-header-search-tools-row">
              <PageHeaderSearchInput
                placeholder="Поиск по чатам..."
                value={search}
                onChange={(e) => setChatsSearch(e.target.value)}
                onDismiss={() => setChatsSearch("")}
              />
              <div className="page-header-scope-select page-header-toolbar--desktop">
                <PageHeaderSelect {...chatsScopeSelectProps} />
              </div>
            </div>
          }
        />
      }
    >
      <ChatsFilterRow />
      <ChatsList data={data} actions={actions} />
    </ScreenShell>
  );
}

"use client";

import { postTitle } from "@/shared/lib/helpers";
import { buildSidebarRecentSections } from "@/widgets/sidebar/lib/buildSidebarRecentSections";
import type { useSidebar } from "@/widgets/sidebar/model/useSidebar";
import { SidebarNavItem } from "@/widgets/sidebar/ui/SidebarNavItem";
import { SidebarRecentList } from "@/widgets/sidebar/ui/SidebarRecentList";
import { SidebarRecentRow } from "@/widgets/sidebar/ui/sidebar-recent-row";
import {
  NavIconAnalytics,
  NavIconChats,
  NavIconFeed,
  NavIconNotes,
  NavIconPlus,
} from "@/shared/ui/nav-icons";
import { SidebarChevron } from "@/widgets/sidebar/ui/SidebarChevron";

type SidebarNavProps = {
  sb: ReturnType<typeof useSidebar>;
};

export function SidebarNav({ sb }: SidebarNavProps) {
  const { chatItems, chatGrouped, noteItems, noteGrouped } = buildSidebarRecentSections(sb);

  return (
    <>
      <SidebarNavItem
        id="home"
        as="button"
        label="Глобальный чат"
        icon={<NavIconPlus />}
        active={sb.isScreenActive("home")}
        onClick={sb.goHome}
      />
      <SidebarNavItem
        id="analytics"
        label="Аналитика"
        icon={<NavIconAnalytics />}
        active={sb.isScreenActive("analytics")}
        onClick={() => sb.navigateScreen("analytics")}
      />
      <SidebarNavItem
        id="feed"
        label="Лента"
        icon={<NavIconFeed />}
        active={sb.isScreenActive("feed")}
        onClick={() => sb.navigateScreen("feed")}
      />

      {sb.showFeedPostRow && sb.currentPostSidebar ? (
        <SidebarRecentRow
          item={{
            key: `post-${sb.currentPostSidebar.id}`,
            title: postTitle(sb.currentPostSidebar),
            active: sb.isSidebarPostFullActive,
            subActive: sb.isSidebarPostSubActive,
            onOpen: () => sb.openPost(sb.currentPostSidebar!.id),
            menuOpen: sb.feedPostMenuOpen,
            onMenuOpenChange: sb.setFeedPostMenuOpen,
            menuItems: sb.feedPostCtxItems,
            wrapSection: true,
          }}
        />
      ) : null}

      <div
        id="nav-notes"
        className={`nav-item nav-item--chats-row${sb.isScreenActive("notes") || sb.isScreenActive("note") ? " active" : ""}`}
      >
        <button type="button" className="nav-item-chats-main" onClick={sb.openNotesNav}>
          <span className="nav-icon">
            <NavIconNotes />
          </span>
          <span className="nav-label">Заметки</span>
        </button>
        <SidebarChevron
          expanded={sb.notesExpanded}
          label={sb.notesExpanded ? "Свернуть список заметок" : "Развернуть список заметок"}
          onToggle={() => sb.setNotesExpanded((value) => !value)}
        />
      </div>
      {sb.notesExpanded ? (
        <SidebarRecentList
          items={noteItems}
          grouped={noteGrouped}
          emptyLabel="Заметок нет"
        />
      ) : null}

      <div
        className={`nav-item nav-item--chats-row${sb.isScreenActive("chats") || sb.isScreenActive("gchat") ? " active" : ""}`}
      >
        <button type="button" className="nav-item-chats-main" onClick={sb.openChatsNav}>
          <span className="nav-icon">
            <NavIconChats />
          </span>
          <span className="nav-label">Чаты</span>
        </button>
        <SidebarChevron
          expanded={sb.chatsExpanded}
          label={sb.chatsExpanded ? "Свернуть список чатов" : "Развернуть список чатов"}
          onToggle={() => sb.setChatsExpanded((value) => !value)}
        />
      </div>
      {sb.chatsExpanded ? (
        <SidebarRecentList
          items={chatItems}
          grouped={chatGrouped}
          emptyLabel="Чатов нет"
        />
      ) : null}
    </>
  );
}

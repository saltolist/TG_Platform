"use client";

import { MessageRenameIcon, MessageTrashIcon } from "@/entities/message";
import { ContextMenu, type CtxMenuItem } from "@/shared/ui/context-menu";
import { confirmDialog } from "@/shared/ui/dialog";

export type SidebarRecentRowKind = "chat" | "note";

export type SidebarRecentRowItem = {
  key: string;
  title: string;
  active?: boolean;
  subActive?: boolean;
  onOpen: () => void;
  menuOpen?: boolean;
  onMenuOpenChange?: (open: boolean) => void;
  onRename?: (title: string) => void;
  onDelete?: () => void;
  kind?: SidebarRecentRowKind;
  menuItems?: CtxMenuItem[];
  wrapSection?: boolean;
};

type SidebarRecentRowProps = {
  item: SidebarRecentRowItem;
};

function rowClassName(item: SidebarRecentRowItem): string {
  const activeClass = item.active ? " active" : item.subActive ? " sub-active" : "";
  const menuClass = item.menuOpen ? " nav-recent-chat-row--menu" : "";
  return `nav-recent-chat-row${activeClass}${menuClass}`;
}

export function SidebarRecentRow({ item }: SidebarRecentRowProps) {
  const hasBuiltInMenu =
    item.menuItems == null &&
    item.onRename != null &&
    item.onDelete != null &&
    item.onMenuOpenChange != null;
  const hasCustomMenu = item.menuItems != null && item.onMenuOpenChange != null;
  const renamePrompt =
    item.kind === "note" ? "Новое название заметки" : "Новое название чата";
  const deleteLabel = item.kind === "note" ? "Удалить заметку" : "Удалить чат";

  const row = (
    <div className={rowClassName(item)}>
      <button type="button" className="nav-recent-chat" onClick={item.onOpen}>
        <span className="nav-recent-chat-title">{item.title}</span>
      </button>
      {hasCustomMenu ? (
        <ContextMenu
          className="nav-recent-chat-ctx"
          align="left"
          portal
          onOpenChange={item.onMenuOpenChange}
          trigger={<span className="nav-recent-chat-dots">⋯</span>}
          items={item.menuItems!}
        />
      ) : null}
      {hasBuiltInMenu ? (
        <ContextMenu
          className="nav-recent-chat-ctx"
          align="left"
          portal
          onOpenChange={item.onMenuOpenChange}
          trigger={<span className="nav-recent-chat-dots">⋯</span>}
          items={[
            {
              label: "Переименовать",
              icon: <MessageRenameIcon />,
              onClick: () => {
                const next = window.prompt(renamePrompt, item.title);
                if (next == null) return;
                const t = next.trim();
                if (!t) return;
                item.onRename?.(t);
              },
            },
            {
              label: deleteLabel,
              icon: <MessageTrashIcon />,
              danger: true,
              onClick: () => {
                void (async () => {
                  const ok = await confirmDialog({
                    message: `Удалить ${item.kind === "note" ? "заметку" : "чат"} «${item.title}»?`,
                    confirmLabel: "Удалить",
                    destructive: true,
                  });
                  if (!ok) return;
                  item.onDelete?.();
                })();
              },
            },
          ]}
        />
      ) : null}
    </div>
  );

  if (item.wrapSection) {
    return <div className="nav-recent-chats">{row}</div>;
  }

  return row;
}

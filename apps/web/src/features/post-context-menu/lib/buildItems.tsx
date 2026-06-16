import type { CtxMenuItem } from "@/shared/ui/context-menu";
import {
  MenuIconCancel,
  MenuIconClock,
  MenuIconPlus,
  MenuIconPublish,
  MenuIconTrash,
} from "@/shared/ui/icons/header-menu-icons";
import type { Post } from "@/shared/types";

export type PostCtxHandlers = {
  onNewChat: () => void;
  onNewNote: () => void;
  onPublish: () => void;
  onSchedule: () => void;
  onReschedule: () => void;
  onCancelPublish: () => void;
  onDelete: () => void;
};

export function getDefaultScheduleDate(): Date {
  const now = new Date();
  now.setMinutes(now.getMinutes() + 30);
  now.setSeconds(0, 0);
  return now;
}

export function buildPostCtxMenuItems(post: Post, handlers: PostCtxHandlers): CtxMenuItem[] {
  const items: CtxMenuItem[] = [
    { label: "Новый чат", icon: <MenuIconPlus />, onClick: handlers.onNewChat },
    { label: "Новая заметка", icon: <MenuIconPlus />, onClick: handlers.onNewNote },
  ];
  if (post.status === "draft") {
    items.push(
      { label: "Опубликовать", icon: <MenuIconPublish />, onClick: handlers.onPublish },
      { label: "Запланировать", icon: <MenuIconClock />, onClick: handlers.onSchedule },
    );
  }
  if (post.status === "scheduled") {
    items.push(
      { label: "Опубликовать", icon: <MenuIconPublish />, onClick: handlers.onPublish },
      { label: "Перенести публикацию", icon: <MenuIconClock />, onClick: handlers.onReschedule },
      { label: "Отменить публикацию", icon: <MenuIconCancel />, onClick: handlers.onCancelPublish },
    );
  }
  items.push({
    label: "Удалить",
    icon: <MenuIconTrash />,
    danger: true,
    onClick: handlers.onDelete,
  });
  return items;
}

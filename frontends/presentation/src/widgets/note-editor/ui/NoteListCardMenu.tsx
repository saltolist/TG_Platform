"use client";

import type { CtxMenuItem } from "@/shared/ui/context-menu";
import { CardContextMenu } from "@/shared/ui/card-menu";
import { useDeleteNote } from "@/features/delete-note";
import { useRenameNote } from "@/features/rename-note";
import { MessageRenameIcon, MessageTrashIcon } from "@/entities/message";

type Props =
  | { isGlobal: true; noteId: string; title: string }
  | { isGlobal: false; postId: string; noteId: string; title: string };

export default function NoteListCardMenu(props: Props) {
  const renameNote = useRenameNote();
  const deleteNote = useDeleteNote();
  const { title } = props;

  const items: CtxMenuItem[] = [
    {
      label: "Переименовать",
      icon: <MessageRenameIcon />,
      onClick: () => renameNote(props, title),
    },
    {
      label: "Удалить",
      icon: <MessageTrashIcon />,
      danger: true,
      onClick: () => deleteNote({ ...props, title }),
    },
  ];

  return <CardContextMenu items={items} ariaLabel="Действия с заметкой" />;
}

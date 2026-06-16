"use client";

import { MessageRenameIcon, MessageTrashIcon } from "@/entities/message";
import { isOmnichannelChatId } from "@/shared/lib/omnichannel";
import type { CtxMenuItem } from "@/shared/ui/context-menu";
import { CardContextMenu } from "@/shared/ui/card-menu";
import { useDeleteChat } from "@/features/delete-chat";
import { useRenameChat } from "@/features/rename-chat";

type Props =
  | { scope: "global"; chatId: string; title: string }
  | { scope: "local"; postId: string; chatId: string; title: string };

export default function ChatListCardMenu(props: Props) {
  const renameChat = useRenameChat();
  const deleteChat = useDeleteChat();
  const { title } = props;

  const isOmnichannel = props.scope === "global" && isOmnichannelChatId(props.chatId);

  const items: CtxMenuItem[] = [
    {
      label: "Переименовать",
      icon: <MessageRenameIcon />,
      onClick: () => renameChat(props, title),
    },
    ...(isOmnichannel
      ? []
      : [
          {
            label: "Удалить",
            icon: <MessageTrashIcon />,
            danger: true,
            onClick: () => deleteChat({ ...props, title }),
          },
        ]),
  ];

  return <CardContextMenu items={items} ariaLabel="Действия с чатом" />;
}

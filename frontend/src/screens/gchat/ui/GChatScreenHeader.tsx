"use client";

import { MenuIconTrash } from "@/shared/ui/icons/header-menu-icons";
import { PageHeader } from "@/widgets/page-header";
import { GChatBreadcrumb } from "@/screens/gchat/ui/GChatBreadcrumb";

type Props = {
  chatTitle: string;
  omnichannel: boolean;
  showDelete: boolean;
  onNavigateBackToChats: () => void;
  onDeleteChat: () => void;
};

export function GChatScreenHeader({
  chatTitle,
  omnichannel,
  showDelete,
  onNavigateBackToChats,
  onDeleteChat,
}: Props) {
  const deleteItem = {
    label: "Удалить чат",
    icon: <MenuIconTrash />,
    danger: true as const,
    onClick: onDeleteChat,
  };

  return (
    <PageHeader
      left={
        <GChatBreadcrumb
          chatTitle={chatTitle}
          onNavigateBackToChats={onNavigateBackToChats}
        />
      }
      onBack={onNavigateBackToChats}
      overflowItems={
        omnichannel || !showDelete
          ? undefined
          : [deleteItem]
      }
    />
  );
}

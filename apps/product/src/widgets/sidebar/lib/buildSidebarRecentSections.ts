import type { useSidebar } from "@/widgets/sidebar/model/useSidebar";
import { mapChatRows, mapNoteRows } from "@/widgets/sidebar/lib/mapRecentRows";

type SidebarState = ReturnType<typeof useSidebar>;

export function buildSidebarRecentSections(sb: SidebarState) {
  const chatMenu = {
    menuOpenKey: sb.recentMenuOpenKey,
    onMenuOpenKeyChange: sb.setRecentMenuOpenKey,
    onRenameRow: sb.renameRecentChat,
    onDeleteRow: sb.deleteRecentChat,
  };

  const noteMenu = {
    menuOpenKey: sb.recentNotesMenuOpenKey,
    onMenuOpenKeyChange: sb.setRecentNotesMenuOpenKey,
    onRenameRow: sb.renameRecentNote,
    onDeleteRow: sb.deleteRecentNote,
  };

  const chatItems =
    sb.recentChatsModel.mode === "flat"
      ? mapChatRows(sb.recentChatsModel.rows, sb.openChatRow, sb.isRecentChatActive, chatMenu)
      : [];

  const chatGrouped =
    sb.recentChatsModel.mode === "grouped"
      ? {
          thisPost: mapChatRows(
            sb.recentChatsModel.thisPost,
            sb.openChatRow,
            sb.isRecentChatActive,
            chatMenu,
          ),
          others: mapChatRows(
            sb.recentChatsModel.others,
            sb.openChatRow,
            sb.isRecentChatActive,
            chatMenu,
          ),
        }
      : undefined;

  const noteItems =
    sb.recentNotesModel.mode === "flat"
      ? mapNoteRows(sb.recentNotesModel.rows, sb.openNoteRow, sb.isRecentNoteActive, noteMenu)
      : [];

  const noteGrouped =
    sb.recentNotesModel.mode === "grouped"
      ? {
          thisPost: mapNoteRows(
            sb.recentNotesModel.thisPost,
            sb.openNoteRow,
            sb.isRecentNoteActive,
            noteMenu,
          ),
          others: mapNoteRows(
            sb.recentNotesModel.others,
            sb.openNoteRow,
            sb.isRecentNoteActive,
            noteMenu,
          ),
        }
      : undefined;

  return { chatItems, chatGrouped, noteItems, noteGrouped };
}

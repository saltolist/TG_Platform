import type { RecentNoteRow, RecentRow } from "@/widgets/sidebar/model/types";
import type { SidebarRecentRowItem } from "@/widgets/sidebar/ui/sidebar-recent-row";

type RecentMapOptions<TRow extends { key: string; title: string }> = {
  kind: "chat" | "note";
  menuOpenKey: string | null;
  onMenuOpenKeyChange: (key: string | null) => void;
  onRenameRow: (row: TRow, title: string) => void;
  onDeleteRow: (row: TRow) => void;
};

function mapRecentRows<TRow extends { key: string; title: string }>(
  rows: TRow[],
  openRow: (row: TRow) => void,
  isActive: (row: TRow) => boolean,
  menu: RecentMapOptions<TRow>,
): SidebarRecentRowItem[] {
  return rows.map((row) => ({
    key: row.key,
    title: row.title,
    active: isActive(row),
    onOpen: () => openRow(row),
    kind: menu.kind,
    menuOpen: menu.menuOpenKey === row.key,
    onMenuOpenChange: (open) => menu.onMenuOpenKeyChange(open ? row.key : null),
    onRename: (title) => menu.onRenameRow(row, title),
    onDelete: () => menu.onDeleteRow(row),
  }));
}

export function mapChatRows(
  rows: RecentRow[],
  openChatRow: (row: RecentRow) => void,
  isRecentChatActive: (row: RecentRow) => boolean,
  menu: Omit<RecentMapOptions<RecentRow>, "kind">,
): SidebarRecentRowItem[] {
  return mapRecentRows(rows, openChatRow, isRecentChatActive, { ...menu, kind: "chat" });
}

export function mapNoteRows(
  rows: RecentNoteRow[],
  openNoteRow: (row: RecentNoteRow) => void,
  isRecentNoteActive: (row: RecentNoteRow) => boolean,
  menu: Omit<RecentMapOptions<RecentNoteRow>, "kind">,
): SidebarRecentRowItem[] {
  return mapRecentRows(rows, openNoteRow, isRecentNoteActive, { ...menu, kind: "note" });
}

import { confirmDialog } from "@/shared/ui/dialog";
import type { ActiveNote } from "@/shared/types";

const NOTE_LEAVE_MSG =
  "У вас есть несохранённые изменения в заметке. Покинуть страницу без сохранения?";

/** @returns true if navigation may proceed */
export async function confirmLeaveNote(
  note: ActiveNote | null,
  noteDirty: boolean,
): Promise<boolean> {
  if (!note || !noteDirty) return true;
  return confirmDialog({
    message: NOTE_LEAVE_MSG,
    confirmLabel: "Покинуть",
    destructive: true,
  });
}

import { confirmDialog } from "@/shared/ui/dialog";

export const USER_MSG_EDIT_LEAVE_MSG =
  "Вы редактируете сообщение. Покинуть без сохранения?";

const POST_EDIT_LEAVE_MSG = "Вы редактируете пост. Покинуть страницу без сохранения?";

type Session = { discard: () => void };

let activeSession: Session | null = null;

export function registerUserMessageEdit(discard: () => void): void {
  activeSession = { discard };
}

export function unregisterUserMessageEdit(discard: () => void): void {
  if (activeSession?.discard === discard) activeSession = null;
}

export async function confirmDiscardUserMessageEdit(): Promise<boolean> {
  if (!activeSession) return true;
  return confirmDialog({
    message: USER_MSG_EDIT_LEAVE_MSG,
    confirmLabel: "Покинуть",
    destructive: true,
  });
}

export function discardUserMessageEdit(): void {
  activeSession?.discard();
  activeSession = null;
}

export async function confirmDiscardAnyChatEdit(isPostEditing: boolean): Promise<boolean> {
  if (
    isPostEditing &&
    !(await confirmDialog({
      message: POST_EDIT_LEAVE_MSG,
      confirmLabel: "Покинуть",
      destructive: true,
    }))
  ) {
    return false;
  }
  if (!(await confirmDiscardUserMessageEdit())) return false;
  return true;
}

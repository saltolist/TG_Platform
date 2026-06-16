"use client";

import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";

import { useNavigationStore } from "@/app/model/store/navigation-store";
import { useUiStore } from "@/app/model/store";
import { useProfileDraftStore } from "@/app/model/store/profile-draft-store";
import { flushAiModelsAutosave } from "@/shared/lib/profile/aiModelsAutosave";
import { confirmLeaveNote } from "@/shared/lib/noteLeave";
import { screenFromPath } from "@/shared/lib/routes";
import { confirmDialog } from "@/shared/ui/dialog";

function getProfileDirtyState(): {
  dirty: boolean;
  channelDirty: boolean;
  settingsDirty: boolean;
} {
  const dirtyMap = useUiStore.getState().dirtyMap;
  const channelDirty = dirtyMap["profile-channel"];
  const settingsDirty =
    dirtyMap["profile-ai"] || dirtyMap["profile-prompt"] || dirtyMap["profile-telegram"];
  return {
    dirty: channelDirty || settingsDirty,
    channelDirty,
    settingsDirty,
  };
}

export function discardProfileEdits(): void {
  useProfileDraftStore.getState().discardEdits();
  useUiStore.getState().clearProfileDirtyFlags();
}

/** Confirm leaving a dirty note screen. Clears noteDirty on success. */
export async function confirmNoteScreenLeave(): Promise<boolean> {
  if (typeof window === "undefined") return true;
  const pathname = window.location.pathname || "/";
  if (screenFromPath(pathname) !== "note") return true;

  const note = useNavigationStore.getState().currentNote;
  const noteDirty = useUiStore.getState().noteDirty;
  if (!(await confirmLeaveNote(note, noteDirty))) return false;
  useUiStore.getState().setNoteDirty(false);
  return true;
}

/** Confirm leaving a dirty profile screen. Discards unsaved profile edits on success. */
export async function confirmProfileScreenLeave(): Promise<boolean> {
  if (typeof window === "undefined") return true;
  const pathname = window.location.pathname || "/";
  if (screenFromPath(pathname) !== "profile") return true;

  await flushAiModelsAutosave();

  const { dirty, channelDirty, settingsDirty } = getProfileDirtyState();
  if (!dirty) return true;

  let message: string;
  if (channelDirty && settingsDirty) {
    message = "Есть несохранённые изменения в профиле. Покинуть страницу без сохранения?";
  } else if (channelDirty) {
    message =
      "Есть несохранённые изменения в профиле канала. Покинуть страницу без сохранения?";
  } else {
    message =
      "Есть несохранённые изменения в настройках профиля. Покинуть страницу без сохранения?";
  }

  const ok = await confirmDialog({
    message,
    confirmLabel: "Покинуть",
    destructive: true,
  });
  if (!ok) return false;
  discardProfileEdits();
  return true;
}

export async function confirmScreenLeave(): Promise<boolean> {
  if (!(await confirmNoteScreenLeave())) return false;
  if (!(await confirmProfileScreenLeave())) return false;
  return true;
}

export async function guardedPush(
  router: AppRouterInstance,
  href: string,
  options?: { replace?: boolean },
): Promise<boolean> {
  if (!(await confirmScreenLeave())) return false;
  if (options?.replace) router.replace(href);
  else router.push(href);
  return true;
}

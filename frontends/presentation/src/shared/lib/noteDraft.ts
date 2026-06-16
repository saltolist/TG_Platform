import type { ActiveNote, NoteFile } from "@/shared/types";
import { canonicalNoteBody } from "./noteEmbeds";

export function draftNoteTitle(title: string) {
  return title.trim() || "Без названия";
}

export function noteIdentityKey(note: ActiveNote): string {
  return note.isGlobal ? `g-${note.id}` : `p${note.postId}-${note.id}`;
}

/** Стабильное сравнение вложений: без blob-url и прочих полей сессии. */
export function snapshotNoteFiles(files: NoteFile[]) {
  return (Array.isArray(files) ? files : [])
    .map((f) => ({ name: f.name, type: f.type || "file" }))
    .sort((a, b) => a.name.localeCompare(b.name, "ru"));
}

export function buildNoteSnapshot(title: string, body: string, ai: boolean, files: NoteFile[]) {
  return JSON.stringify({
    title: title.trim(),
    body: canonicalNoteBody(body),
    ai,
    files: snapshotNoteFiles(files),
  });
}

/** Обновить только флаг «учитывать в ИИ» в снимке (переключатель в меню шапки). */
export function patchNoteSnapshotAi(snapshot: string, ai: boolean): string {
  try {
    const data = JSON.parse(snapshot) as { ai?: boolean };
    if (data.ai === ai) return snapshot;
    return JSON.stringify({ ...data, ai });
  } catch {
    return snapshot;
  }
}

export const EMPTY_NOTE_SNAPSHOT = buildNoteSnapshot("", "", false, []);

export function isNoteDirty(note: ActiveNote, savedSnapshot: string): boolean {
  const files = Array.isArray(note.files) ? note.files : [];
  return savedSnapshot !== buildNoteSnapshot(note.title, note.body, note.ai, files);
}

export function isNoteImageFile(file: NoteFile): boolean {
  if (file.type?.startsWith("image/")) return true;
  return /\.(png|jpe?g|gif|webp|svg|bmp|avif|heic)$/i.test(file.name);
}

export function createNewGlobalNote(): ActiveNote {
  return {
    id: "gn-new",
    title: "",
    body: "",
    ai: false,
    date: new Date().toISOString(),
    isGlobal: true,
    files: [],
    isNew: true,
  };
}

export function createNewPostNote(postId: string): ActiveNote {
  return {
    id: "",
    title: "",
    body: "",
    ai: false,
    date: new Date().toISOString(),
    isGlobal: false,
    postId,
    files: [],
    isNew: true,
  };
}

import { isNoteImageFile } from "@/shared/lib/noteDraft";
import type { NoteFile } from "@/shared/types";

export function findNoteFile(files: NoteFile[], name: string): NoteFile | undefined {
  return files.find((f) => f.name === name);
}

export function isImageEmbed(file: NoteFile | undefined): boolean {
  return !!file && isNoteImageFile(file);
}

import { z } from "zod";
import { noteFileSchema } from "./post";

/** BlockNote document JSON — the editor's source of truth (body is derived for RAG). */
export const noteDocSchema = z.array(z.unknown());

export const globalNoteSchema = z.object({
  id: z.string(),
  title: z.string(),
  ai: z.boolean(),
  date: z.string(),
  body: z.string(),
  doc: noteDocSchema.optional(),
  files: z.array(noteFileSchema).optional(),
});

export const globalNotesListSchema = z.array(globalNoteSchema);

export type GlobalNote = z.infer<typeof globalNoteSchema>;

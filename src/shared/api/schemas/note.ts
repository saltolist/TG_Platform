import { z } from "zod";
import { noteFileSchema } from "./post";

export const globalNoteSchema = z.object({
  id: z.string(),
  title: z.string(),
  ai: z.boolean(),
  date: z.string(),
  body: z.string(),
  files: z.array(noteFileSchema).optional(),
});

export const globalNotesListSchema = z.array(globalNoteSchema);

export type GlobalNote = z.infer<typeof globalNoteSchema>;

import { z } from "zod";
import { chatMessageSchema } from "./post";
import { chatContextMetaSchema } from "./chatContextMeta";

export const globalChatKindSchema = z.enum(["default", "omnichannel"]);

export const globalChatSchema = chatContextMetaSchema.extend({
  id: z.string(),
  kind: globalChatKindSchema.optional(),
  title: z.string(),
  preview: z.string(),
  date: z.string(),
  history: z.array(chatMessageSchema),
});

export const globalChatsListSchema = z.array(globalChatSchema);

export type GlobalChatKind = z.infer<typeof globalChatKindSchema>;
export type GlobalChat = z.infer<typeof globalChatSchema>;

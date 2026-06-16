import { z } from "zod";

export const postStatusSchema = z.enum(["published", "scheduled", "draft"]);

export const postReactionSchema = z.object({
  emoji: z.string(),
  count: z.number(),
});

export const postMetricsSchema = z.object({
  views: z.string(),
  reposts: z.number(),
  reactions: z.array(postReactionSchema),
});

export const postMediaSchema = z.object({
  name: z.string(),
  url: z.string(),
  type: z.string(),
});

export const noteFileSchema = z.object({
  id: z.string().optional(),
  name: z.string(),
  type: z.string(),
  url: z.string().optional(),
});

export const localNoteSchema = z.object({
  id: z.string(),
  title: z.string(),
  date: z.string(),
  ai: z.boolean(),
  body: z.string(),
  files: z.array(noteFileSchema).optional(),
});

export const aiVariantSchema = z.object({
  key: z.string(),
  label: z.string(),
  text: z.string(),
  llmCaption: z.string().optional(),
  webCaption: z.string().optional(),
});

export const userMessageBranchSchema = z.object({
  text: z.string(),
  continuation: z.lazy(() => z.array(chatMessageSchema)),
});

export const chatMessageSchema: z.ZodType<{
  role: "user" | "ai";
  text?: string;
  userBranches?: z.infer<typeof userMessageBranchSchema>[];
  activeUserBranch?: number;
  variants?: z.infer<typeof aiVariantSchema>[];
  selectedVariant?: number;
  mode?: "single" | "multi";
  targetLabel?: string;
  llmLabel?: string;
  webLabel?: string;
}> = z.lazy(() =>
  z.object({
    role: z.enum(["user", "ai"]),
    text: z.string().optional(),
    userBranches: z.array(userMessageBranchSchema).optional(),
    activeUserBranch: z.number().optional(),
    variants: z.array(aiVariantSchema).optional(),
    selectedVariant: z.number().optional(),
    mode: z.enum(["single", "multi"]).optional(),
    targetLabel: z.string().optional(),
    llmLabel: z.string().optional(),
    webLabel: z.string().optional(),
  }),
);

export const localChatSchema = z.object({
  id: z.string(),
  title: z.string(),
  preview: z.string(),
  date: z.string(),
  history: z.array(chatMessageSchema),
  ai: z.boolean(),
});

export const postCommentSchema = z.object({
  id: z.string(),
  author: z.string(),
  text: z.string(),
  date: z.string(),
  replyToId: z.string().optional(),
  media: z.array(postMediaSchema).optional(),
});

export const postSchema = z.object({
  id: z.string(),
  status: postStatusSchema,
  date: z.string().optional(),
  created: z.string().optional(),
  rubric: z.string().nullable(),
  metrics: postMetricsSchema.optional(),
  text: z.string(),
  media: z.array(postMediaSchema).optional(),
  notes: z.array(localNoteSchema),
  chats: z.array(localChatSchema),
  comments: z.array(postCommentSchema).optional(),
});

export const postsListSchema = z.array(postSchema);

export type PostStatus = z.infer<typeof postStatusSchema>;
export type PostReaction = z.infer<typeof postReactionSchema>;
export type PostMetrics = z.infer<typeof postMetricsSchema>;
export type PostMedia = z.infer<typeof postMediaSchema>;
export type NoteFile = z.infer<typeof noteFileSchema>;
export type LocalNote = z.infer<typeof localNoteSchema>;
export type AiVariant = z.infer<typeof aiVariantSchema>;
export type UserMessageBranch = z.infer<typeof userMessageBranchSchema>;
export type ChatMessage = z.infer<typeof chatMessageSchema>;
export type LocalChat = z.infer<typeof localChatSchema>;
export type PostComment = z.infer<typeof postCommentSchema>;
export type Post = z.infer<typeof postSchema>;

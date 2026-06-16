export type ChatMessageCtx =
  | { scope: "gchat"; entityId: string; path: number[] }
  | { scope: "post"; postId: string; entityId: string; path: number[] };

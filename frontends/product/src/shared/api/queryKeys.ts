export const queryKeys = {
  scope: (accountId: string) => ["account", accountId] as const,
  posts: {
    all: (accountId: string) => [...queryKeys.scope(accountId), "posts"] as const,
    list: (accountId: string) => [...queryKeys.posts.all(accountId), "list"] as const,
    detail: (accountId: string, id: string) =>
      [...queryKeys.posts.all(accountId), "detail", id] as const,
  },
  globalChats: {
    all: (accountId: string) => [...queryKeys.scope(accountId), "globalChats"] as const,
    list: (accountId: string) => [...queryKeys.globalChats.all(accountId), "list"] as const,
    detail: (accountId: string, id: string) =>
      [...queryKeys.globalChats.all(accountId), "detail", id] as const,
  },
  globalNotes: {
    all: (accountId: string) => [...queryKeys.scope(accountId), "globalNotes"] as const,
    list: (accountId: string) => [...queryKeys.globalNotes.all(accountId), "list"] as const,
    detail: (accountId: string, id: string) =>
      [...queryKeys.globalNotes.all(accountId), "detail", id] as const,
  },
  profile: {
    all: (accountId: string) => [...queryKeys.scope(accountId), "profile"] as const,
    channel: (accountId: string) => [...queryKeys.profile.all(accountId), "channel"] as const,
    ai: (accountId: string) => [...queryKeys.profile.all(accountId), "ai"] as const,
    telegram: (accountId: string) => [...queryKeys.profile.all(accountId), "telegram"] as const,
  },
} as const;

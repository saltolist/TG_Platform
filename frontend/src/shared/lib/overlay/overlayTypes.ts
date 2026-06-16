import type {
  AiProfileConfig,
  ChannelProfileConfig,
  GlobalChat,
  GlobalNote,
  Post,
  TelegramProfileConfig,
} from "@/shared/types";

export type EntityOverlay<T extends { id: string }> = {
  upserts: Record<string, T>;
  removedIds: string[];
};

export type AccountOverlay = {
  posts: EntityOverlay<Post> & { order?: string[] };
  globalChats: EntityOverlay<GlobalChat>;
  globalNotes: EntityOverlay<GlobalNote>;
  profile?: {
    channel?: ChannelProfileConfig;
    ai?: AiProfileConfig;
    telegram?: TelegramProfileConfig;
  };
};

export function createEmptyOverlay(): AccountOverlay {
  return {
    posts: { upserts: {}, removedIds: [] },
    globalChats: { upserts: {}, removedIds: [] },
    globalNotes: { upserts: {}, removedIds: [] },
  };
}

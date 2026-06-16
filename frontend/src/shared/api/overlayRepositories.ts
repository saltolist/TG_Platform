import { normalizeAiProfileConfig } from "@/shared/lib/profile/aiModelsSnapshot";
import { isOverlayAccount } from "@/shared/lib/overlay/isOverlayAccount";
import { mergeEntityList } from "@/shared/lib/overlay/mergeEntities";
import { mutateOverlay, readOverlay } from "@/shared/lib/overlay/overlayStorage";
import type {
  ChatsRepository,
  GlobalChatPatch,
  NotesRepository,
  PostsRepository,
  ProfileRepository,
  RepositoryBundle,
} from "@/shared/api/repositories";
import type {
  AiProfileConfig,
  ChannelProfileConfig,
  GlobalChat,
  GlobalNote,
  Post,
  TelegramProfileConfig,
} from "@/shared/types";

function overlayPosts(inner: PostsRepository): PostsRepository {
  return {
    list: async () => {
      const base = await inner.list();
      if (!isOverlayAccount()) return base;
      const overlay = readOverlay();
      return mergeEntityList(base, overlay.posts, overlay.posts.order);
    },
    create: async (post) => {
      if (!isOverlayAccount()) return inner.create(post);
      mutateOverlay((overlay) => {
        overlay.posts.upserts[post.id] = post;
        const order = overlay.posts.order ?? [];
        overlay.posts.order = [post.id, ...order.filter((id) => id !== post.id)];
      });
      return post;
    },
    update: async (id, patch) => {
      if (!isOverlayAccount()) return inner.update(id, patch);
      const list = await overlayPosts(inner).list();
      const current = list.find((post) => post.id === id);
      if (!current) throw new Error(`Post ${id} not found`);
      const updated = { ...current, ...patch };
      mutateOverlay((overlay) => {
        overlay.posts.upserts[id] = updated;
      });
      return updated;
    },
    reorder: async (posts) => {
      if (!isOverlayAccount()) return inner.reorder(posts);
      mutateOverlay((overlay) => {
        overlay.posts.order = posts.map((post) => post.id);
        for (const post of posts) {
          overlay.posts.upserts[post.id] = post;
        }
      });
      return posts;
    },
    remove: async (id) => {
      if (!isOverlayAccount()) return inner.remove(id);
      mutateOverlay((overlay) => {
        if (!overlay.posts.removedIds.includes(id)) {
          overlay.posts.removedIds.push(id);
        }
        delete overlay.posts.upserts[id];
        if (overlay.posts.order) {
          overlay.posts.order = overlay.posts.order.filter((itemId) => itemId !== id);
        }
      });
    },
  };
}

function overlayChats(inner: ChatsRepository): ChatsRepository {
  const listMerged = async (): Promise<GlobalChat[]> => {
    const base = await inner.listGlobal();
    if (!isOverlayAccount()) return base;
    const overlay = readOverlay();
    return mergeEntityList(base, overlay.globalChats);
  };

  return {
    listGlobal: listMerged,
    create: async (chat) => {
      if (!isOverlayAccount()) return inner.create(chat);
      mutateOverlay((overlay) => {
        overlay.globalChats.upserts[chat.id] = chat;
      });
      return chat;
    },
    pushMessage: async (chatId, text) => {
      if (!isOverlayAccount()) return inner.pushMessage(chatId, text);
      const chat = (await listMerged()).find((item) => item.id === chatId);
      if (!chat) throw new Error(`Chat ${chatId} not found`);
      const updated = await overlayChats(inner).update(chatId, {
        history: [...chat.history, { role: "user", text }],
      });
      return updated;
    },
    update: async (chatId, patch) => {
      if (!isOverlayAccount()) return inner.update(chatId, patch);
      const list = await listMerged();
      const current = list.find((chat) => chat.id === chatId);
      if (!current) throw new Error(`Chat ${chatId} not found`);
      const updated = { ...current, ...patch };
      mutateOverlay((overlay) => {
        overlay.globalChats.upserts[chatId] = updated;
      });
      return updated;
    },
    rename: async (chatId, title) => overlayChats(inner).update(chatId, { title }),
    remove: async (chatId) => {
      if (!isOverlayAccount()) return inner.remove(chatId);
      mutateOverlay((overlay) => {
        if (!overlay.globalChats.removedIds.includes(chatId)) {
          overlay.globalChats.removedIds.push(chatId);
        }
        delete overlay.globalChats.upserts[chatId];
      });
    },
  };
}

function overlayNotes(inner: NotesRepository): NotesRepository {
  return {
    listGlobal: async () => {
      const base = await inner.listGlobal();
      if (!isOverlayAccount()) return base;
      const overlay = readOverlay();
      return mergeEntityList(base, overlay.globalNotes);
    },
    upsert: async (note) => {
      if (!isOverlayAccount()) return inner.upsert(note);
      mutateOverlay((overlay) => {
        overlay.globalNotes.upserts[note.id] = note;
      });
      return note;
    },
    remove: async (noteId) => {
      if (!isOverlayAccount()) return inner.remove(noteId);
      mutateOverlay((overlay) => {
        if (!overlay.globalNotes.removedIds.includes(noteId)) {
          overlay.globalNotes.removedIds.push(noteId);
        }
        delete overlay.globalNotes.upserts[noteId];
      });
    },
  };
}

function overlayProfile(inner: ProfileRepository): ProfileRepository {
  return {
    getChannel: async () => {
      const base = await inner.getChannel();
      if (!isOverlayAccount()) return base;
      return readOverlay().profile?.channel ?? base;
    },
    updateChannel: async (config) => {
      if (!isOverlayAccount()) return inner.updateChannel(config);
      mutateOverlay((overlay) => {
        overlay.profile = { ...overlay.profile, channel: config };
      });
      return config;
    },
    getAi: async () => {
      const base = await inner.getAi();
      if (!isOverlayAccount()) return normalizeAiProfileConfig(base);
      return normalizeAiProfileConfig(readOverlay().profile?.ai ?? base);
    },
    updateAi: async (config) => {
      const normalized = normalizeAiProfileConfig(config);
      if (!isOverlayAccount()) return inner.updateAi(normalized);
      mutateOverlay((overlay) => {
        overlay.profile = { ...overlay.profile, ai: normalized };
      });
      return normalized;
    },
    getTelegram: async () => {
      const base = await inner.getTelegram();
      if (!isOverlayAccount()) return base;
      return readOverlay().profile?.telegram ?? base;
    },
    updateTelegram: async (config) => {
      if (!isOverlayAccount()) return inner.updateTelegram(config);
      mutateOverlay((overlay) => {
        overlay.profile = { ...overlay.profile, telegram: config };
      });
      return config;
    },
  };
}

export function createOverlayRepositories(inner: RepositoryBundle): RepositoryBundle {
  return {
    posts: overlayPosts(inner.posts),
    chats: overlayChats(inner.chats),
    notes: overlayNotes(inner.notes),
    profile: overlayProfile(inner.profile),
    assistant: inner.assistant,
  };
}

import { normalizeAiProfileConfig } from "@/shared/lib/profile/aiModelsSnapshot";
import {
  normalizeChannelProfileConfig,
  normalizeTelegramProfileConfig,
} from "@/shared/lib/profile/normalizeProfileConfig";
import { formatConnectedChannelDisplay } from "@/shared/lib/channel/normalizeChannelHandle";
import { shouldPersistLocally } from "@/shared/lib/overlay/isOverlayAccount";
import { mergeEntityList } from "@/shared/lib/overlay/mergeEntities";
import { mutateOverlay, readOverlay } from "@/shared/lib/overlay/overlayStorage";
import { scheduleOverlayNotesSync } from "@/shared/lib/overlay/syncOverlayNotes";
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
      if (!shouldPersistLocally()) return base;
      const overlay = readOverlay();
      return mergeEntityList(base, overlay.posts, overlay.posts.order);
    },
    create: async (post) => {
      if (!shouldPersistLocally()) return inner.create(post);
      mutateOverlay((overlay) => {
        overlay.posts.upserts[post.id] = post;
        const order = overlay.posts.order ?? [];
        overlay.posts.order = [post.id, ...order.filter((id) => id !== post.id)];
      });
      return post;
    },
    update: async (id, patch) => {
      if (!shouldPersistLocally()) return inner.update(id, patch);
      const list = await overlayPosts(inner).list();
      const current = list.find((post) => post.id === id);
      if (!current) throw new Error(`Post ${id} not found`);
      const updated = { ...current, ...patch };
      mutateOverlay((overlay) => {
        overlay.posts.upserts[id] = updated;
      });
      scheduleOverlayNotesSync();
      return updated;
    },
    reorder: async (posts) => {
      if (!shouldPersistLocally()) return inner.reorder(posts);
      mutateOverlay((overlay) => {
        overlay.posts.order = posts.map((post) => post.id);
        for (const post of posts) {
          overlay.posts.upserts[post.id] = post;
        }
      });
      return posts;
    },
    remove: async (id) => {
      if (!shouldPersistLocally()) return inner.remove(id);
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
    if (!shouldPersistLocally()) return base;
    const overlay = readOverlay();
    return mergeEntityList(base, overlay.globalChats);
  };

  return {
    listGlobal: listMerged,
    create: async (chat) => {
      if (!shouldPersistLocally()) return inner.create(chat);
      mutateOverlay((overlay) => {
        overlay.globalChats.upserts[chat.id] = chat;
      });
      return chat;
    },
    pushMessage: async (chatId, text) => {
      if (!shouldPersistLocally()) return inner.pushMessage(chatId, text);
      const chat = (await listMerged()).find((item) => item.id === chatId);
      if (!chat) throw new Error(`Chat ${chatId} not found`);
      const updated = await overlayChats(inner).update(chatId, {
        history: [...chat.history, { role: "user", text }],
      });
      return updated;
    },
    update: async (chatId, patch) => {
      if (!shouldPersistLocally()) return inner.update(chatId, patch);
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
      if (!shouldPersistLocally()) return inner.remove(chatId);
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
      if (!shouldPersistLocally()) return base;
      const overlay = readOverlay();
      return mergeEntityList(base, overlay.globalNotes);
    },
    upsert: async (note) => {
      if (!shouldPersistLocally()) return inner.upsert(note);
      mutateOverlay((overlay) => {
        overlay.globalNotes.upserts[note.id] = note;
      });
      scheduleOverlayNotesSync();
      return note;
    },
    remove: async (noteId) => {
      if (!shouldPersistLocally()) return inner.remove(noteId);
      mutateOverlay((overlay) => {
        if (!overlay.globalNotes.removedIds.includes(noteId)) {
          overlay.globalNotes.removedIds.push(noteId);
        }
        delete overlay.globalNotes.upserts[noteId];
      });
      scheduleOverlayNotesSync();
    },
  };
}

function overlayProfile(inner: ProfileRepository): ProfileRepository {
  return {
    getChannel: async () => {
      const base = normalizeChannelProfileConfig(await inner.getChannel());
      if (!shouldPersistLocally()) return base;
      const overlay = readOverlay().profile?.channel;
      return overlay ? normalizeChannelProfileConfig({ ...base, ...overlay }) : base;
    },
    updateChannel: async (config) => {
      const normalized = normalizeChannelProfileConfig(config);
      const saved = normalizeChannelProfileConfig(await inner.updateChannel(normalized));
      if (shouldPersistLocally()) {
        mutateOverlay((overlay) => {
          overlay.profile = { ...overlay.profile, channel: saved };
        });
      }
      return saved;
    },
    getAi: async () => {
      const base = await inner.getAi();
      if (!shouldPersistLocally()) return normalizeAiProfileConfig(base);
      return normalizeAiProfileConfig(readOverlay().profile?.ai ?? base);
    },
    updateAi: async (config) => {
      const normalized = normalizeAiProfileConfig(config);
      if (!shouldPersistLocally()) return inner.updateAi(normalized);
      mutateOverlay((overlay) => {
        overlay.profile = { ...overlay.profile, ai: normalized };
      });
      return normalized;
    },
    revealAiModelApiKey: (modelId, field) => inner.revealAiModelApiKey(modelId, field),
    revealTelegramSecret: (field) => inner.revealTelegramSecret(field),
    getTelegram: async () => {
      const base = normalizeTelegramProfileConfig(await inner.getTelegram());
      if (!shouldPersistLocally()) return base;
      const overlay = readOverlay().profile?.telegram;
      return overlay ? normalizeTelegramProfileConfig({ ...base, ...overlay }) : base;
    },
    updateTelegram: async (config) => {
      if (!shouldPersistLocally()) return inner.updateTelegram(config);
      mutateOverlay((overlay) => {
        overlay.profile = { ...overlay.profile, telegram: config };
      });
      return config;
    },
    // The real MTProto flow below only makes sense for real Telegram accounts.
    // Guest/demo overlay accounts (and MSW dev mode in general) never had real
    // credentials to begin with, so we keep the previous "always succeeds
    // instantly" simulation, now living here instead of in the React hook.
    sendTelegramCode: async (phone) => {
      if (!shouldPersistLocally()) return inner.sendTelegramCode(phone);
      const current = normalizeTelegramProfileConfig(await overlayProfile(inner).getTelegram());
      const next = normalizeTelegramProfileConfig({
        ...current,
        phone,
        authStatus: "code-sent",
        authStep: "code",
      });
      mutateOverlay((overlay) => {
        overlay.profile = { ...overlay.profile, telegram: next };
      });
      return next;
    },
    verifyTelegramCode: async (code) => {
      if (!shouldPersistLocally()) return inner.verifyTelegramCode(code);
      if (!code.trim()) throw new Error("Укажите код из Telegram");
      const current = normalizeTelegramProfileConfig(await overlayProfile(inner).getTelegram());
      const next = normalizeTelegramProfileConfig({
        ...current,
        authStatus: "authorized",
        authStep: "channel",
        sessionString: `overlay-session-${Date.now()}`,
      });
      mutateOverlay((overlay) => {
        overlay.profile = { ...overlay.profile, telegram: next };
      });
      return next;
    },
    verifyTelegram2fa: async (password) => {
      if (!shouldPersistLocally()) return inner.verifyTelegram2fa(password);
      if (!password.trim()) throw new Error("Укажите пароль");
      const current = normalizeTelegramProfileConfig(await overlayProfile(inner).getTelegram());
      const next = normalizeTelegramProfileConfig({
        ...current,
        authStatus: "authorized",
        authStep: "channel",
        sessionString: `overlay-session-${Date.now()}`,
      });
      mutateOverlay((overlay) => {
        overlay.profile = { ...overlay.profile, telegram: next };
      });
      return next;
    },
    resetTelegramAuth: async () => {
      if (!shouldPersistLocally()) return inner.resetTelegramAuth();
      const current = normalizeTelegramProfileConfig(await overlayProfile(inner).getTelegram());
      const next = normalizeTelegramProfileConfig({
        ...current,
        authStatus: "idle",
        authStep: "credentials",
        sessionString: "",
      });
      mutateOverlay((overlay) => {
        overlay.profile = { ...overlay.profile, telegram: next };
      });
      return next;
    },
    connectTelegramChannel: async (channel) => {
      if (!shouldPersistLocally()) return inner.connectTelegramChannel(channel);
      const display = formatConnectedChannelDisplay(channel);
      if (!display) throw new Error("Укажите канал");
      const current = normalizeTelegramProfileConfig(await overlayProfile(inner).getTelegram());
      const next = normalizeTelegramProfileConfig({
        ...current,
        channel: display,
        channelTitle: display,
        channelId: `overlay-channel-${Date.now()}`,
        channelStatus: "connected",
        authStatus: "connected",
        authStep: "connected",
        lastSync: new Date().toISOString(),
        importStatus: "done",
        importError: "",
        syncStatus: "listening",
        syncError: "",
        importedPosts: 42,
      });
      mutateOverlay((overlay) => {
        overlay.profile = { ...overlay.profile, telegram: next };
      });
      return next;
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
    analytics: inner.analytics,
  };
}

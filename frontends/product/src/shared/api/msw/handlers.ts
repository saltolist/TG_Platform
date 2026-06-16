import { http, HttpResponse } from "msw";
import { apiV1MswPath } from "@/shared/config/basePath";
import { DEMO_CHANNEL_TITLE } from "@/shared/lib/auth/constants";
import { appendToActiveHistory } from "@/shared/lib/chatPaths";
import { getGlobalReply, getPostReply } from "@/shared/api/assistantReplies";
import type { GlobalChat, GlobalNote, Post, TelegramProfileConfig } from "@/shared/types";
import {
  getStoreForRequest,
  importDemoKanalPosts,
  isDemoKanalHandle,
} from "./accountRegistry";
import { authHandlers } from "./authHandlers";

function notFound(message: string) {
  return HttpResponse.json({ error: message }, { status: 404 });
}

function unauthorized() {
  return HttpResponse.json({ error: "Unauthorized" }, { status: 401 });
}

function requireStore(request: Request) {
  return getStoreForRequest(request);
}

export const handlers = [
  ...authHandlers,

  http.get(apiV1MswPath("posts"), ({ request }) => {
    const store = requireStore(request);
    if (!store) return unauthorized();
    return HttpResponse.json(store.posts);
  }),

  http.post(apiV1MswPath("posts"), async ({ request }) => {
    const store = requireStore(request);
    if (!store) return unauthorized();
    const post = (await request.json()) as Post;
    store.posts = [post, ...store.posts.filter((p) => p.id !== post.id)];
    return HttpResponse.json(post, { status: 201 });
  }),

  http.patch(apiV1MswPath("posts/:id"), async ({ params, request }) => {
    const store = requireStore(request);
    if (!store) return unauthorized();
    const id = String(params.id);
    const patch = (await request.json()) as Partial<Post>;
    const idx = store.posts.findIndex((p) => p.id === id);
    if (idx < 0) return notFound(`Post ${id} not found`);
    store.posts[idx] = { ...store.posts[idx], ...patch };
    return HttpResponse.json(store.posts[idx]);
  }),

  http.put(apiV1MswPath("posts/reorder"), async ({ request }) => {
    const store = requireStore(request);
    if (!store) return unauthorized();
    const body = (await request.json()) as { posts: Post[] };
    store.posts = [...body.posts];
    return HttpResponse.json(store.posts);
  }),

  http.delete(apiV1MswPath("posts/:id"), ({ params, request }) => {
    const store = requireStore(request);
    if (!store) return unauthorized();
    const id = String(params.id);
    const before = store.posts.length;
    store.posts = store.posts.filter((p) => p.id !== id);
    if (store.posts.length === before) return notFound(`Post ${id} not found`);
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(apiV1MswPath("global-chats"), ({ request }) => {
    const store = requireStore(request);
    if (!store) return unauthorized();
    return HttpResponse.json(store.globalChats);
  }),

  http.post(apiV1MswPath("global-chats"), async ({ request }) => {
    const store = requireStore(request);
    if (!store) return unauthorized();
    const chat = (await request.json()) as GlobalChat;
    store.globalChats = [chat, ...store.globalChats.filter((c) => c.id !== chat.id)];
    return HttpResponse.json(chat, { status: 201 });
  }),

  http.post(apiV1MswPath("global-chats/:chatId/messages"), async ({ params, request }) => {
    const store = requireStore(request);
    if (!store) return unauthorized();
    const chatId = String(params.chatId);
    const { text } = (await request.json()) as { text: string };
    const chat = store.globalChats.find((c) => c.id === chatId);
    if (!chat) return notFound(`Chat ${chatId} not found`);

    const aiText = getGlobalReply(text);
    let history = appendToActiveHistory(chat.history, { role: "user", text });
    history = appendToActiveHistory(history, {
      role: "ai",
      text: aiText,
      llmLabel: "OpenAI / gpt-4o",
      webLabel: "Perplexity / search-api",
    });
    const updated: GlobalChat = {
      ...chat,
      history,
      preview: aiText.slice(0, 80),
      date: new Date().toISOString(),
    };
    store.globalChats = store.globalChats.map((c) => (c.id === chatId ? updated : c));
    return HttpResponse.json(updated);
  }),

  http.patch(apiV1MswPath("global-chats/:chatId"), async ({ params, request }) => {
    const store = requireStore(request);
    if (!store) return unauthorized();
    const chatId = String(params.chatId);
    const patch = (await request.json()) as Partial<GlobalChat>;
    const chat = store.globalChats.find((c) => c.id === chatId);
    if (!chat) return notFound(`Chat ${chatId} not found`);
    const updated = { ...chat, ...patch };
    store.globalChats = store.globalChats.map((c) => (c.id === chatId ? updated : c));
    return HttpResponse.json(updated);
  }),

  http.delete(apiV1MswPath("global-chats/:chatId"), ({ params, request }) => {
    const store = requireStore(request);
    if (!store) return unauthorized();
    const chatId = String(params.chatId);
    const before = store.globalChats.length;
    store.globalChats = store.globalChats.filter((c) => c.id !== chatId);
    if (store.globalChats.length === before) return notFound(`Chat ${chatId} not found`);
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(apiV1MswPath("global-notes"), ({ request }) => {
    const store = requireStore(request);
    if (!store) return unauthorized();
    return HttpResponse.json(store.globalNotes);
  }),

  http.put(apiV1MswPath("global-notes/:noteId"), async ({ params, request }) => {
    const store = requireStore(request);
    if (!store) return unauthorized();
    const noteId = String(params.noteId);
    const note = (await request.json()) as GlobalNote;
    if (note.id !== noteId) {
      return HttpResponse.json({ error: "Note id mismatch" }, { status: 400 });
    }
    const exists = store.globalNotes.some((n) => n.id === noteId);
    store.globalNotes = exists
      ? store.globalNotes.map((n) => (n.id === noteId ? note : n))
      : [note, ...store.globalNotes];
    return HttpResponse.json(note);
  }),

  http.delete(apiV1MswPath("global-notes/:noteId"), ({ params, request }) => {
    const store = requireStore(request);
    if (!store) return unauthorized();
    const noteId = String(params.noteId);
    const before = store.globalNotes.length;
    store.globalNotes = store.globalNotes.filter((n) => n.id !== noteId);
    if (store.globalNotes.length === before) return notFound(`Note ${noteId} not found`);
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(apiV1MswPath("profile/channel"), ({ request }) => {
    const store = requireStore(request);
    if (!store) return unauthorized();
    return HttpResponse.json(store.channelProfile);
  }),

  http.put(apiV1MswPath("profile/channel"), async ({ request }) => {
    const store = requireStore(request);
    if (!store) return unauthorized();
    store.channelProfile = (await request.json()) as typeof store.channelProfile;
    return HttpResponse.json(store.channelProfile);
  }),

  http.get(apiV1MswPath("profile/ai"), ({ request }) => {
    const store = requireStore(request);
    if (!store) return unauthorized();
    return HttpResponse.json(store.aiProfile);
  }),

  http.put(apiV1MswPath("profile/ai"), async ({ request }) => {
    const store = requireStore(request);
    if (!store) return unauthorized();
    store.aiProfile = (await request.json()) as typeof store.aiProfile;
    return HttpResponse.json(store.aiProfile);
  }),

  http.get(apiV1MswPath("profile/telegram"), ({ request }) => {
    const store = requireStore(request);
    if (!store) return unauthorized();
    return HttpResponse.json(store.telegramProfile);
  }),

  http.put(apiV1MswPath("profile/telegram"), async ({ request }) => {
    const store = requireStore(request);
    if (!store) return unauthorized();
    const next = (await request.json()) as TelegramProfileConfig;
    const wasConnected = store.telegramProfile.channelStatus === "connected";
    store.telegramProfile = next;

    if (
      !wasConnected &&
      next.channelStatus === "connected" &&
      isDemoKanalHandle(next.channel)
    ) {
      const count = importDemoKanalPosts(store);
      store.telegramProfile.importedPosts = count;
      store.telegramProfile.lastSync = new Date().toISOString();
      store.telegramProfile.channelTitle = DEMO_CHANNEL_TITLE;
    }

    return HttpResponse.json(store.telegramProfile);
  }),

  http.post(apiV1MswPath("ai/reply"), async ({ request }) => {
    const store = requireStore(request);
    if (!store) return unauthorized();
    const body = (await request.json()) as { text: string; scope: "global" | "post" };
    await new Promise((resolve) => setTimeout(resolve, 300));
    const text =
      body.scope === "post" ? getPostReply(body.text) : getGlobalReply(body.text);
    return HttpResponse.json({ text });
  }),
];

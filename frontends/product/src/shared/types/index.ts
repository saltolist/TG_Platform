import type {
  AiVariant,
  ChatMessage,
  GlobalChat,
  GlobalChatKind,
  GlobalNote,
  LocalChat,
  LocalNote,
  NoteFile,
  Post,
  PostComment,
  PostMedia,
  PostMetrics,
  PostReaction,
  PostStatus,
  UserMessageBranch,
} from "@/shared/api/schemas";

export type {
  Post,
  PostStatus,
  PostReaction,
  PostMetrics,
  PostMedia,
  NoteFile,
  LocalNote,
  LocalChat,
  PostComment,
  ChatMessage,
  AiVariant,
  UserMessageBranch,
  GlobalChat,
  GlobalChatKind,
  GlobalNote,
} from "@/shared/api/schemas";

export type ScreenId =
  | "home"
  | "gchat"
  | "feed"
  | "post"
  | "note"
  | "chats"
  | "notes"
  | "analytics"
  | "profile";

export type ComposerScope = "home" | "gchat" | "post";

export type ChatRole = "user" | "ai";

export type LlmModel = {
  id: string;
  provider: string;
  model: string;
  apiKey: string;
  active: boolean;
  includeInMulti: boolean;
};

export type WebSearchModel = LlmModel;

export type ChannelProfileRubric = {
  id: string;
  title: string;
  description: string;
};

export type ChannelProfileConfig = {
  core: {
    topic: string;
    audience: string;
    promise: string;
    angle: string;
    author: string;
  };
  voice: {
    tone: string;
    format: string;
    phrases: string;
  };
  rules: {
    must: string;
    avoid: string;
  };
  rubrics: ChannelProfileRubric[];
};

export type AiProfileConfig = {
  llmModels: LlmModel[];
  webSearchModels: WebSearchModel[];
  visionModels: LlmModel[];
  imageGenerationModels: LlmModel[];
  orchestratorModels: LlmModel[];
  webReasonerModels: LlmModel[];
  ragReasonerModels: LlmModel[];
  multiResponseEnabled: boolean;
  systemPrompt: string;
};

export type TelegramAuthStatus = "idle" | "code-sent" | "authorized" | "connected";
export type TelegramChannelStatus = "idle" | "pending" | "connected";
export type TelegramSyncMode = "live-only" | "history-and-live" | "publish-only";

export type TelegramBotStatus = "idle" | "connected";

export type TelegramProfileConfig = {
  authStatus: TelegramAuthStatus;
  authStep: string;
  apiId: string;
  apiHash: string;
  phone: string;
  sessionName: string;
  channel: string;
  channelTitle: string;
  channelStatus: TelegramChannelStatus;
  syncMode: TelegramSyncMode;
  lastSync: string;
  importedPosts: number;
  botApiToken: string;
  botStatus: TelegramBotStatus;
  botUsername: string;
  botLastActivity: string;
  botMessageCount: number;
};

export type ComposerTarget = { llmId: string; webId: string };

export type ChatsTab = "all" | "global" | "local";
export type NoteScope = "all" | "global" | "local";
export type NoteListFilter = "all" | "ai" | "noai";
export type PostMode = "chat" | "chats" | "notes" | "comments";
export type NoteMode = "view" | "edit";
export type NoteFromScreen = "notes" | "post";

export type ActiveNote =
  | (GlobalNote & { isGlobal: true; files: NoteFile[]; isNew?: boolean })
  | (LocalNote & { isGlobal: false; postId: string; files: NoteFile[]; isNew?: boolean });

export type ComposerAttachment =
  | { id: string; kind: "post"; postId: string; title: string }
  | { id: string; kind: "file"; name: string; file?: File }
  | { id: string; kind: "media"; postId: string; postTitle: string; media: string };

export type ThemeMode = "light" | "system" | "dark";

export type { FeedCardWidth, FeedPostWidth } from "@/shared/lib/feedPostWidth";

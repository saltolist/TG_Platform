import type {
  AiProfileConfig,
  ChannelProfileConfig,
  GlobalChat,
  GlobalNote,
  Post,
  TelegramProfileConfig,
} from "@/shared/types";

export type GlobalChatPatch = Partial<
  Pick<GlobalChat, "title" | "preview" | "date" | "history">
>;

export interface PostsRepository {
  list(): Promise<Post[]>;
  create(post: Post): Promise<Post>;
  update(id: string, patch: Partial<Post>): Promise<Post>;
  reorder(posts: Post[]): Promise<Post[]>;
  remove(id: string): Promise<void>;
}

export interface ChatsRepository {
  listGlobal(): Promise<GlobalChat[]>;
  create(chat: GlobalChat): Promise<GlobalChat>;
  pushMessage(chatId: string, text: string): Promise<GlobalChat>;
  update(chatId: string, patch: GlobalChatPatch): Promise<GlobalChat>;
  rename(chatId: string, title: string): Promise<GlobalChat>;
  remove(chatId: string): Promise<void>;
}

export interface NotesRepository {
  listGlobal(): Promise<GlobalNote[]>;
  upsert(note: GlobalNote): Promise<GlobalNote>;
  remove(noteId: string): Promise<void>;
}

export interface ProfileRepository {
  getChannel(): Promise<ChannelProfileConfig>;
  updateChannel(config: ChannelProfileConfig): Promise<ChannelProfileConfig>;
  getAi(): Promise<AiProfileConfig>;
  updateAi(config: AiProfileConfig): Promise<AiProfileConfig>;
  getTelegram(): Promise<TelegramProfileConfig>;
  updateTelegram(config: TelegramProfileConfig): Promise<TelegramProfileConfig>;
}

export type AssistantStreamOptions = {
  llmId?: string;
  signal?: AbortSignal;
};

export interface AssistantRepository {
  streamGlobalChatReply(
    text: string,
    onChunk: (chunk: string) => void,
    options?: AssistantStreamOptions,
  ): Promise<string>;
  streamPostChatReply(
    text: string,
    onChunk: (chunk: string) => void,
    options?: AssistantStreamOptions,
  ): Promise<string>;
  getGlobalChatReply(text: string, options?: AssistantStreamOptions): Promise<string>;
  getPostChatReply(text: string, options?: AssistantStreamOptions): Promise<string>;
}

export type RepositoryBundle = {
  posts: PostsRepository;
  chats: ChatsRepository;
  notes: NotesRepository;
  profile: ProfileRepository;
  assistant: AssistantRepository;
};

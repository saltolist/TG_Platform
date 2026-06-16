import type {
  AiProfileConfig,
  ChannelProfileConfig,
  TelegramProfileConfig,
} from "@/shared/types";
import { DEMO_CHANNEL_HANDLE } from "@/shared/lib/auth/constants";
import type { MswStore } from "@/shared/api/msw/store";

function emptyChannelProfile(): ChannelProfileConfig {
  return {
    core: {
      topic: "",
      audience: "",
      promise: "",
      angle: "",
      author: "",
    },
    voice: {
      tone: "",
      format: "",
      phrases: "",
    },
    rules: {
      must: "",
      avoid: "",
    },
    rubrics: [],
  };
}

function emptyAiProfile(): AiProfileConfig {
  return {
    llmModels: [],
    webSearchModels: [],
    visionModels: [],
    imageGenerationModels: [],
    orchestratorModels: [],
    webReasonerModels: [],
    ragReasonerModels: [],
    multiResponseEnabled: false,
    systemPrompt: "",
  };
}

function emptyTelegramProfile(): TelegramProfileConfig {
  return {
    authStatus: "idle",
    authStep: "credentials",
    apiId: "",
    apiHash: "",
    phone: "",
    sessionName: "",
    /** Prefilled for onboarding; channel block appears after phone code is confirmed. */
    channel: DEMO_CHANNEL_HANDLE,
    channelTitle: "",
    channelStatus: "idle",
    syncMode: "history-and-live",
    lastSync: "—",
    importedPosts: 0,
    botApiToken: "",
    botStatus: "idle",
    botUsername: "",
    botLastActivity: "—",
    botMessageCount: 0,
  };
}

export function createEmptyAccountStore(): MswStore {
  return {
    posts: [],
    globalChats: [],
    globalNotes: [],
    channelProfile: emptyChannelProfile(),
    aiProfile: emptyAiProfile(),
    telegramProfile: emptyTelegramProfile(),
  };
}

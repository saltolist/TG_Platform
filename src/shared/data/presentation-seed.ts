import type {
  AiProfileConfig,
  ChannelProfileConfig,
  GlobalChat,
  GlobalNote,
  Post,
  TelegramProfileConfig,
} from "@/shared/types";
import { themedPostMedia } from "@/shared/data/demo-media";
import {
  PRESENTATION_CHANNEL_HANDLE,
  PRESENTATION_CHANNEL_TITLE,
} from "@/shared/lib/auth/constants";
import type { MswStore } from "@/shared/api/msw/store";

export const PRESENTATION_POST_IDS = ["21", "22", "23", "24", "25", "26", "27", "28", "29"] as const;
export const PRESENTATION_GLOBAL_NOTE_IDS = ["pn1", "pn2", "pn3"] as const;
export const PRESENTATION_GLOBAL_CHAT_IDS = ["pc1", "pc2"] as const;

const mediaWelcome = themedPostMedia("IMG_2101.jpg", "workspace-hub");

const mediaFeedA = themedPostMedia("IMG_2102.jpg", "feed-timeline");
const mediaFeedB = themedPostMedia("IMG_2103.jpg", "feed-sections");

const mediaNotesA = themedPostMedia("IMG_2104.jpg", "notes-stack");
const mediaNotesB = themedPostMedia("IMG_2105.jpg", "ai-dialogue");

const mediaAnalyticsA = themedPostMedia("IMG_2107.jpg", "chart-growth");
const mediaAnalyticsB = themedPostMedia("IMG_2108.jpg", "heatmap-grid");

const mediaScheduleIntro = themedPostMedia("IMG_2111.jpg", "clock-pending");
const mediaScheduleHowA = themedPostMedia("IMG_2112.jpg", "calendar-slot");
const mediaScheduleHowB = themedPostMedia("IMG_2113.jpg", "postpone-flow");

const mediaDraftIntro = themedPostMedia("IMG_2114.jpg", "draft-post-edit");
const mediaDraftDndA = themedPostMedia("IMG_2115.jpg", "draft-top-handle");
const mediaDraftDndB = themedPostMedia("IMG_2116.jpg", "draft-reorder");

const presentationPosts: Post[] = [
  {
    id: "21",
    status: "published",
    date: "2026-06-10T10:00:00.000Z",
    rubric: "Обзор",
    metrics: {
      views: "1 240",
      reposts: 8,
      reactions: [
        { emoji: "👋", count: 42 },
        { emoji: "✨", count: 18 },
      ],
    },
    text: `Добро пожаловать в TG Platform — рабочее пространство для автора Telegram-канала.

Здесь вы ведёте ленту, планируете публикации, собираете заметки и общаетесь с ИИ в контексте канала. Всё в одном интерфейсе: без переключения между десятком сервисов.

Это демо-канал «Презентация»: посты ниже показывают, как устроена платформа. Нажмите «Войти» внизу слева, чтобы создать свой аккаунт или войти в демо.`,
    media: [mediaWelcome],
    notes: [],
    comments: [],
    chats: [],
  },
  {
    id: "22",
    status: "published",
    date: "2026-06-11T11:15:00.000Z",
    rubric: "Лента",
    metrics: { views: "980", reposts: 5, reactions: [{ emoji: "📰", count: 31 }] },
    text: `Лента — центр работы с контентом канала.

✦ Опубликованные посты сгруппированы по дням
✦ Черновики и отложенные публикации — отдельные секции
✦ Композер внизу: текст, медиа и быстрая отправка в черновик
✦ Клик по посту открывает чат, заметки и комментарии

После подключения своего Telegram-канала в настройках сюда подтягиваются реальные публикации.`,
    media: [mediaFeedA, mediaFeedB],
    notes: [],
    comments: [],
    chats: [],
  },
  {
    id: "23",
    status: "published",
    date: "2026-06-12T10:30:00.000Z",
    rubric: "ИИ",
    metrics: { views: "860", reposts: 4, reactions: [{ emoji: "🤖", count: 27 }] },
    text: `Заметки и чаты с ИИ помогают готовить контент осознанно.

Заметки бывают глобальными (для всего канала) и локальными (привязаны к посту). Чаты — глобальные обсуждения и локальные диалоги внутри поста.

ИИ видит базу знаний канала, системный промпт и выбранные модели из настроек. Вы сами решаете, какие заметки включать в контекст.`,
    media: [mediaNotesA, mediaNotesB],
    notes: [],
    comments: [],
    chats: [],
  },
  {
    id: "24",
    status: "published",
    date: "2026-06-12T14:00:00.000Z",
    rubric: "Аналитика",
    metrics: { views: "720", reposts: 3, reactions: [{ emoji: "📊", count: 19 }] },
    text: `Аналитика и настройки закрывают цикл «планирую → публикую → смотрю результат».

В разделе аналитики — динамика канала, тепловая карта активности и топ постов. В профиле — подключение Telegram, ИИ-движок, база знаний канала и метрики использования моделей.

Создайте аккаунт через «Войти», подключите канал и начните с чистого листа — или войдите в полное демо с готовым наполнением.`,
    media: [mediaAnalyticsA, mediaAnalyticsB],
    notes: [],
    comments: [],
    chats: [],
  },
  {
    id: "25",
    status: "scheduled",
    date: "2026-06-14T12:00:00.000Z",
    rubric: "Планирование",
    text: `Посты можно откладывать — не обязательно публиковать сразу.

Отложенная публикация удобна, когда текст уже готов, а выходить он должен в конкретный день и час: утренний дайджест, вечерний разбор, пост к событию.

В ленте такие посты живут в отдельной секции «Отложенные» — их видно до выхода, можно отредактировать или перенести время.`,
    media: [mediaScheduleIntro],
    notes: [],
    comments: [],
    chats: [],
  },
  {
    id: "26",
    status: "scheduled",
    date: "2026-06-17T18:00:00.000Z",
    rubric: "Планирование",
    text: `Как устроено откладывание в TG Platform:

1. Создайте пост или откройте черновик
2. В меню поста выберите «Отложить» и укажите дату с временем
3. Пост попадёт в секцию отложенных — с иконкой часов и меткой времени
4. В нужный момент публикация уйдёт в канал (после подключения Telegram)

Так же можно перенести уже отложенный пост или вернуть его в черновик.`,
    media: [mediaScheduleHowA, mediaScheduleHowB],
    notes: [],
    comments: [],
    chats: [],
  },
  {
    id: "27",
    status: "draft",
    created: "2026-06-12T00:00:00.000Z",
    rubric: "Черновики",
    text: `Черновики — место для незавершённых идей.

Текст можно дописывать сколько угодно, прикреплять медиа и не бояться случайной публикации. Черновик не виден подписчикам, пока вы сами не опубликуете или не отложите его.

Создать черновик: напишите в композере внизу ленты и нажмите «В черновик» — карточка появится в секции «Черновики».`,
    media: [mediaDraftIntro],
    notes: [],
    comments: [],
    chats: [],
  },
  {
    id: "28",
    status: "draft",
    created: "2026-06-12T00:00:00.000Z",
    rubric: "Черновики",
    text: `Черновики в ленте можно менять местами перетаскиванием.

Сверху по центру карточки — ручка из шести точек (сетка 3×2). Зажмите её и потяните черновик вверх или вниз: порядок в секции «Черновики» обновится. Так удобно выстраивать очередь публикаций или контент-план.

Тянуть нужно именно за ручку — клик по тексту по-прежнему открывает пост.`,
    media: [mediaDraftDndA, mediaDraftDndB],
    notes: [],
    comments: [],
    chats: [],
  },
  {
    id: "29",
    status: "draft",
    created: "2026-06-12T00:00:00.000Z",
    rubric: "Контент-план",
    text: `Так можно собирать контент-план прямо в ленте.

Держите в черновиках заготовки на неделю: темы, тезисы, черновые тексты. Когда материал готов — публикуйте сразу или откладывайте на нужный день.

Черновик → правки → отложенная публикация → аналитика после выхода. Весь цикл в одном интерфейсе, без таблиц и сторонних сервисов.`,
    notes: [],
    comments: [],
    chats: [],
  },
];

const presentationGlobalNotes: GlobalNote[] = [
  {
    id: "pn1",
    title: "С чего начать на платформе",
    ai: true,
    date: "2026-06-12T00:00:00.000Z",
    body:
      "1. Изучите ленту и боковое меню\n2. Откройте заметки и чаты — там примеры работы с ИИ\n3. Загляните в аналитику\n4. Нажмите «Войти» и зарегистрируйте аккаунт\n5. В профиле подключите Telegram-канал",
  },
  {
    id: "pn2",
    title: "Навигация и разделы",
    ai: false,
    date: "2026-06-12T00:00:00.000Z",
    body:
      "Главная — быстрый глобальный чат. Лента — посты канала. Чаты и заметки — личное рабочее пространство. Аналитика — метрики канала. Профиль доступен после входа.",
  },
  {
    id: "pn3",
    title: "ИИ-движок в двух словах",
    ai: true,
    date: "2026-06-12T00:00:00.000Z",
    body:
      "В настройках профиля задаются LLM, веб-поиск, оркестраторы и системный промпт. База знаний канала — на отдельной вкладке. Каждый аккаунт настраивает ИИ под себя.",
  },
];

const presentationGlobalChats: GlobalChat[] = [
  {
    id: "pc1",
    title: "Что умеет TG Platform?",
    preview: "Кратко перечисли возможности платформы для автора канала",
    date: "2026-06-12T00:00:00.000Z",
    history: [
      { role: "user", text: "Кратко перечисли возможности платформы для автора канала" },
      {
        role: "ai",
        llmLabel: "OpenAI / gpt-4o",
        text:
          "TG Platform объединяет ленту постов, планирование публикаций, заметки, чаты с ИИ, аналитику канала и настройки Telegram + ИИ-движка. Всё заточено под ежедневную работу автора, а не под разовую генерацию текста.",
      },
    ],
  },
  {
    id: "pc2",
    title: "Как перейти к своему аккаунту?",
    preview: "Я смотрю демо — что делать дальше?",
    date: "2026-06-12T00:00:00.000Z",
    history: [
      { role: "user", text: "Я смотрю демо — что делать дальше?" },
      {
        role: "ai",
        llmLabel: "OpenAI / gpt-4o",
        text:
          "Нажмите «Войти» внизу бокового меню. Можно зарегистрировать новый аккаунт или войти в полное демо (demo@mail.ru). После входа подключите свой Telegram-канал в настройках профиля.",
      },
    ],
  },
];

const emptyChannelProfile = (): ChannelProfileConfig => ({
  core: {
    topic: "Платформа TG Platform для авторов Telegram-каналов",
    audience:
      "Авторы каналов, которые хотят понять возможности продукта до регистрации: лента, заметки, чаты с ИИ, аналитика и подключение Telegram",
    promise:
      "Краткий обзор того, как платформа помогает вести канал в одном рабочем пространстве — без обязательства сразу подключать свой канал",
    angle:
      "Демо-канал «Презентация» показывает интерфейс и сценарии работы; после входа можно подключить свой Telegram или войти в полное демо",
    author:
      "Команда TG Platform. Это не реальный авторский канал — материалы объясняют разделы продукта и типовые сценарии использования.",
  },
  voice: {
    tone: "Спокойный, понятный, без жаргона и без давления",
    format: "Короткие абзацы, списки с одним видом эмодзи, выводы можно выделять жирным",
    phrases: "Обращение на «вы»; без «народ», «ребят» и агрессивных продаж",
  },
  rules: {
    must: "Объяснять разделы платформы на примерах из интерфейса",
    avoid: "Обещания доходности, финансовые советы, кликбейт",
  },
  rubrics: [
    {
      id: "rubric-overview",
      title: "Обзор",
      description: "Что умеет платформа и с чего начать.",
    },
    {
      id: "rubric-workflow",
      title: "Рабочий процесс",
      description: "Лента, заметки, чаты и аналитика в одном месте.",
    },
    {
      id: "rubric-planning",
      title: "Планирование",
      description: "Черновики и отложенные публикации.",
    },
  ],
});

const presentationAiProfile = (): AiProfileConfig => ({
  llmModels: [
    {
      id: "llm-presentation-openai",
      provider: "OpenAI",
      model: "gpt-4o",
      apiKey: "sk-openai-demo",
      active: true,
      includeInMulti: true,
    },
    {
      id: "llm-presentation-claude",
      provider: "Anthropic",
      model: "claude-3-7-sonnet",
      apiKey: "sk-anthropic-demo",
      active: true,
      includeInMulti: false,
    },
  ],
  webSearchModels: [
    {
      id: "web-presentation-tavily",
      provider: "Tavily",
      model: "search-v1",
      apiKey: "tvly-demo",
      active: true,
      includeInMulti: true,
    },
    {
      id: "web-presentation-exa",
      provider: "Exa",
      model: "exa-neural",
      apiKey: "exa-demo",
      active: true,
      includeInMulti: false,
    },
    {
      id: "web-presentation-responses",
      provider: "OpenAI",
      model: "responses-api-web-search",
      apiKey: "sk-openai-demo",
      active: true,
      includeInMulti: false,
    },
  ],
  visionModels: [],
  imageGenerationModels: [],
  orchestratorModels: [],
  webReasonerModels: [],
  ragReasonerModels: [],
  multiResponseEnabled: false,
  systemPrompt:
    "Ты помощник на демо-канале «Презентация». Кратко объясняй возможности TG Platform и подсказывай нажать «Войти», чтобы создать свой аккаунт.",
});

const presentationTelegramProfile = (): TelegramProfileConfig => ({
  authStatus: "connected",
  authStep: "connected",
  apiId: "",
  apiHash: "",
  phone: "",
  sessionName: "",
  channel: PRESENTATION_CHANNEL_HANDLE,
  channelTitle: PRESENTATION_CHANNEL_TITLE,
  channelStatus: "connected",
  syncMode: "history-and-live",
  lastSync: "2026-06-16T12:40:00.000Z",
  importedPosts: presentationPosts.length,
  botApiToken: "",
  botStatus: "idle",
  botUsername: "",
  botLastActivity: "—",
  botMessageCount: 0,
});

export function createPresentationMswStore(): MswStore {
  return {
    posts: structuredClone(presentationPosts),
    globalChats: structuredClone(presentationGlobalChats),
    globalNotes: structuredClone(presentationGlobalNotes),
    channelProfile: emptyChannelProfile(),
    aiProfile: presentationAiProfile(),
    telegramProfile: presentationTelegramProfile(),
  };
}

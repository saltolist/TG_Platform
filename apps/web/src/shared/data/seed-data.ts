import type {
  AiProfileConfig,
  ChannelProfileConfig,
  GlobalChat,
  GlobalNote,
  Post,
  TelegramProfileConfig,
} from "@/shared/types";
import {
  mediaBuyButton,
  mediaFirstStep,
  mediaIisA,
  mediaIisB,
} from "@/shared/data/seed-post-media";

export const initialPosts: Post[] = [
  {
    id: "1",
    status: "published",
    date: "2026-04-28T14:22:00.000Z",
    rubric: null,
    metrics: {
      views: "5 100",
      reposts: 23,
      reactions: [
        { emoji: "🔥", count: 412 },
        { emoji: "❤️", count: 89 },
        { emoji: "👍", count: 56 },
        { emoji: "🤔", count: 34 },
        { emoji: "👏", count: 21 },
      ],
    },
    text: `Два года я не мог нажать кнопку "Открыть счёт". Не потому что не было денег. Просто мозг не пускал.

Это называется "паралич анализа" — когда знаешь что делать, понимаешь зачем, но всё равно откладываешь.

Вот что мне помогло:

1. Убрал "правильность" из уравнения. Нет идеального момента.
2. Сделал минимальный шаг — 1 000 рублей в индекс.
3. Перестал читать прогнозы.`,
    media: [mediaFirstStep],
    notes: [
      {
        id: "101",
        title: "Барьер №2 — первая сделка",
        date: "2026-04-29T00:00:00.000Z",
        ai: false,
        body: "Следующий барьер после открытия счёта — первая сделка.",
      },
      {
        id: "102",
        title: "Альтернативный финал поста",
        date: "2026-04-28T00:00:00.000Z",
        ai: false,
        body: "Другой финал: сфокусироваться на маленьком шаге.",
      },
      {
        id: "103",
        title: "Факты для поста про ИИС",
        date: "2026-04-27T00:00:00.000Z",
        ai: true,
        body: "Налоговый вычет типа А: до 52 000 руб/год.",
      },
    ],
    comments: [
      {
        id: "10001",
        author: "Елена М.",
        date: "2026-04-28T14:22:00.000Z",
        text: "Узнала себя в первом абзаце. Три года откладывала открытие счёта — думала, что «ещё не готова».",
      },
      {
        id: "10002",
        author: "Дмитрий С.",
        date: "2026-04-28T15:01:00.000Z",
        replyToId: "10001",
        text: "Пункт про 1 000 рублей — лучший совет. Сделал так же, через неделю уже не страшно.",
      },
      {
        id: "10003",
        author: "Ирина В.",
        date: "2026-04-28T16:44:00.000Z",
        text: "А если счёт уже открыт, но на кнопку «Купить» всё равно не нажимается?",
      },
      {
        id: "10004",
        author: "Автор канала",
        date: "2026-04-28T17:02:00.000Z",
        replyToId: "10003",
        text: "Ирина, это как раз тема следующего поста — первая сделка отдельный психологический порог.",
      },
      {
        id: "10005",
        author: "Олег Н.",
        date: "2026-04-28T19:18:00.000Z",
        text: "Перестал читать прогнозы полгода назад — стало спокойнее. Спасибо, что озвучил это вслух.",
      },
      {
        id: "10006",
        author: "Мария Т.",
        date: "2026-04-29T09:05:00.000Z",
        replyToId: "10005",
        text: "Поддерживаю. Новости только усиливают FOMO.",
      },
    ],
    chats: [
      {
        id: "1001",
        title: "Почему пост зашёл",
        preview: "Этот пост работает лучше обычного. Как думаешь, почему?",
        date: "2026-04-29T00:00:00.000Z",
        ai: true,
        history: [
          { role: "user", text: "Этот пост работает лучше обычного. Как думаешь, почему?" },
          {
            role: "ai",
            llmLabel: "OpenAI / gpt-4o",
            webLabel: "Perplexity / search-api",
            text:
              "По паттернам канала — посты от первого лица с личной историей преодоления страха получают на 35% больше охватов. Здесь сработало три вещи: конкретный числовой заголовок, универсальная боль аудитории и практичные шаги в конце.",
          },
        ],
      },
    ],
  },
  {
    id: "2",
    status: "published",
    date: "2026-04-25T11:10:00.000Z",
    rubric: null,
    metrics: {
      views: "4 200",
      reposts: 18,
      reactions: [
        { emoji: "👍", count: 142 },
        { emoji: "❤️", count: 38 },
        { emoji: "📌", count: 15 },
        { emoji: "🎯", count: 9 },
      ],
    },
    text: `ИИС пугает людей аббревиатурой. Расшифруем: индивидуальный инвестиционный счёт.

Две причины открыть прямо сейчас:
→ Налоговый вычет типа А: возвращаешь до 52 000 рублей в год.
→ Типа Б: освобождение прибыли от налогов.

Минус один: деньги нужно держать 3 года.`,
    media: [mediaIisA, mediaIisB],
    notes: [],
    chats: [],
    comments: [
      {
        id: "20001",
        author: "Павел К.",
        date: "2026-04-25T11:10:00.000Z",
        text: "Наконец понял разницу между типом А и Б. Можно коротко: кому что выгоднее?",
      },
      {
        id: "20002",
        author: "Автор канала",
        date: "2026-04-25T11:28:00.000Z",
        replyToId: "20001",
        text: "Если планируешь выводить прибыль — чаще тип А. Если копить долго и не трогать — тип Б.",
      },
      {
        id: "20003",
        author: "Светлана Р.",
        date: "2026-04-25T12:40:00.000Z",
        text: "А три года — это жёстко. Есть ли способ выйти раньше без потери вычета?",
      },
      {
        id: "20004",
        author: "Никита Л.",
        date: "2026-04-25T14:15:00.000Z",
        replyToId: "20003",
        text: "Досрочное закрытие = возврат вычетов и налог с прибыли. Лучше не открывать, если не уверен.",
      },
    ],
  },
  {
    id: "5",
    status: "published",
    date: "2026-04-28T17:12:00.000Z",
    rubric: null,
    metrics: {
      views: "1 840",
      reposts: 6,
      reactions: [
        { emoji: "👍", count: 24 },
        { emoji: "💡", count: 11 },
        { emoji: "❤️", count: 7 },
      ],
    },
    text: `Держал кэш три месяца «на случай просадки». Просадка пришла — и я всё равно не купил.

Оказалось, дело не в рынке. Я ждал не лучшей цены, а ощущения, что «сейчас точно безопасно».

С тех пор правило одно: маленький лот по плану раз в две недели. Без новостей и без попыток угадать дно.`,
    notes: [],
    chats: [],
  },
  {
    id: "3",
    status: "scheduled",
    date: "2026-05-05T19:00:00.000Z",
    rubric: null,
    text: `Ты уже открыл счёт. Теперь смотришь на кнопку "Купить" — и снова что-то останавливает.

Первая сделка — это особый психологический порог.`,
    media: [mediaBuyButton],
    notes: [],
    chats: [],
  },
  {
    id: "4",
    status: "draft",
    created: "2026-05-01T00:00:00.000Z",
    rubric: null,
    text: "Апрель закрыт. Разбираю что покупал и почему.",
    notes: [],
    chats: [],
  },
];

export const initialGlobalChats: GlobalChat[] = [
  {
    id: "gc1",
    title: "Анализ недели",
    preview: "Три поста за неделю. Лучший...",
    date: "2026-05-01T00:00:00.000Z",
    history: [
      { role: "user", text: "Проанализируй эту неделю" },
      {
        role: "ai",
        llmLabel: "OpenAI / gpt-4o",
        webLabel: "Perplexity / search-api",
        text:
          'Три поста за неделю. Лучший — "Синдром чистого листа" (+34% к среднему). Рубрика "Психология денег" обогнала "Разбор" по охватам второй раз подряд.',
      },
    ],
  },
  {
    id: "gc2",
    title: "Контент-план на май",
    preview: "Составь контент-план на следующую...",
    date: "2026-04-28T00:00:00.000Z",
    history: [
      { role: "user", text: "Составь контент-план на следующую неделю" },
      {
        role: "ai",
        llmLabel: "OpenAI / gpt-4o",
        webLabel: "Perplexity / search-api",
        text:
          "📅 Пн — «Психология денег»: продолжение серии про барьеры\n📅 Ср — «Разбор»: ошибки начинающих инвесторов\n📅 Пт — «Личный опыт»: что купил в апреле",
      },
    ],
  },
];

export const initialGlobalNotes: GlobalNote[] = [
  {
    id: "gn1",
    title: "Структура серии про барьеры инвестора",
    ai: true,
    date: "2026-05-01T00:00:00.000Z",
    body:
      'Серия "Барьеры инвестора"\n\n1. Синдром чистого листа — открыть счёт\n2. Первая сделка — что и когда купить\n3. Первый убыток — как не паниковать\n4. Регулярные пополнения — автоматизация\n\nФормат: личный опыт + практика',
  },
  { id: "gn2", title: "Мониторинг конкурентов", ai: false, date: "2026-04-28T00:00:00.000Z", body: "Подборка каналов о финансах..." },
  { id: "gn3", title: "Правила канала (расширенные)", ai: true, date: "2026-04-25T00:00:00.000Z", body: "Запреты, тон, структура..." },
  {
    id: "gn4",
    title: "Идеи постов на май",
    ai: false,
    date: "2026-04-20T00:00:00.000Z",
    body: "- Психология сложного %\n- Как читать отчётность\n- Первые ETF",
  },
];

export const initialChannelProfileConfig: ChannelProfileConfig = {
  core: {
    topic: "Личные финансы и инвестиции для начинающих",
    audience:
      "Люди с первыми накоплениями, которые боятся ошибиться и откладывают первый шаг в инвестициях, но хотят разобраться спокойно и без давления",
    promise:
      "Понятные объяснения без жаргона, честный разбор рисков и маленькие шаги, которые можно сделать уже сейчас — без ощущения, что «опоздал»",
    angle:
      "Личная цель автора: выстроить узнаваемый личный бренд в нише, привлечь внимание работодателей и партнёров, монетизировать экспертизу через консультации и продукты, плюс дисциплинировать собственные инвестиции публичными разборами",
    author:
      "Алексей, 34 года, Москва. Работаю продуктовым аналитиком в IT, личный портфель веду с 2016 года — сначала хаотично, потом по правилам, которые сам же и объясняю в канале.\n\nНе финансовый советник и не управляющий: пишу как практик, который прошёл через страх первой покупки, FOMO на «ракетах» и желание «догнать рынок». Делюсь тем, что реально делал: подушка, брокер, ETF, налоги, ошибки с таймингом.\n\nДля читателя — старший товарищ, не гуру: без обещаний доходности и без давления «срочно купи». Личное — в меру: семья и работа упоминаю только если это помогает примеру. Монетизация — консультации и разборы по запросу, в ленте — в первую очередь польза и доверие",
  },
  voice: {
    tone: "Разговорный, уважительный, без канцелярита, хайпа и ощущения продаж",
    format:
      "Длина абзацев: не более 3–4 строк на один абзац. Пустая строка между абзацами обязательна.\n\nСписки: вместо стандартных точек и дефисов используйте тематические эмодзи (но не более одного вида на весь список).\n\nВизуальные акценты: главные мысли, тезисы или выводы ИИ должен выделять жирным шрифтом.\n\nОбъем: максимум 1000–1500 символов. Если текст больше, ИИ должен сократить его или разбить на пункты.",
    phrases:
      "Основное обращение — на «ты», на равных: как к коллеге, который разбирается в теме вместе с читателем. «Вы» — в постах про риски, потери и ответственность за решения. Не использовать «ребят», «друзья», «народ»; без назидания («ты обязан», «слушай сюда»)",
  },
  rules: {
    must: "Объяснять термины сразу, говорить честно о рисках, опираться на бытовые примеры и личный опыт",
    avoid: "Кликбейт, точные прогнозы, обещания доходности, агрессивные продажи, слова: профит, иксы, ракета",
  },
  rubrics: [
    {
      id: "rubric-money-psychology",
      title: "Психология денег",
      description: "Страхи, прокрастинация, FOMO и привычки вокруг денег.",
    },
    {
      id: "rubric-breakdown",
      title: "Разбор",
      description: "Простое объяснение инструмента, налога или рыночного явления.",
    },
    {
      id: "rubric-personal",
      title: "Личный опыт",
      description: "Что автор сделал, где ошибся и какой вывод забрал.",
    },
    {
      id: "rubric-news",
      title: "Новости",
      description: "Спокойный комментарий к финансовой повестке без паники.",
    },
  ],
};

export const initialAiProfileConfig: AiProfileConfig = {
  llmModels: [
    {
      id: "llm-1",
      provider: "OpenAI",
      model: "gpt-4o",
      apiKey: "sk-openai-demo",
      active: true,
      includeInMulti: true,
    },
    {
      id: "llm-2",
      provider: "Anthropic",
      model: "claude-3-7-sonnet",
      apiKey: "sk-anthropic-demo",
      active: true,
      includeInMulti: false,
    },
    {
      id: "llm-3",
      provider: "Perplexity",
      model: "sonar",
      apiKey: "pk-perplexity-demo",
      active: true,
      includeInMulti: false,
    },
    {
      id: "llm-4",
      provider: "Perplexity",
      model: "sonar-pro",
      apiKey: "pk-perplexity-demo",
      active: true,
      includeInMulti: false,
    },
  ],
  webSearchModels: [
    {
      id: "web-1",
      provider: "Perplexity",
      model: "search-api",
      apiKey: "pk-perplexity-demo",
      active: true,
      includeInMulti: true,
    },
    {
      id: "web-2",
      provider: "Tavily",
      model: "search-v1",
      apiKey: "tvly-demo",
      active: true,
      includeInMulti: false,
    },
    {
      id: "web-3",
      provider: "OpenAI",
      model: "responses-api-web-search",
      apiKey: "sk-openai-demo",
      active: true,
      includeInMulti: false,
    },
  ],
  visionModels: [
    {
      id: "vision-1",
      provider: "OpenAI",
      model: "gpt-4o",
      apiKey: "sk-openai-demo",
      active: true,
      includeInMulti: false,
    },
  ],
  imageGenerationModels: [
    {
      id: "image-gen-1",
      provider: "OpenAI",
      model: "dall-e-3",
      apiKey: "sk-openai-demo",
      active: true,
      includeInMulti: false,
    },
  ],
  orchestratorModels: [
    {
      id: "orchestrator-1",
      provider: "OpenAI",
      model: "gpt-4.1",
      apiKey: "sk-openai-demo",
      active: true,
      includeInMulti: false,
    },
  ],
  webReasonerModels: [
    {
      id: "web-reasoner-1",
      provider: "OpenAI",
      model: "gpt-4.1-mini",
      apiKey: "sk-openai-demo",
      active: true,
      includeInMulti: false,
    },
  ],
  ragReasonerModels: [
    {
      id: "rag-reasoner-1",
      provider: "OpenAI",
      model: "gpt-4.1-mini",
      apiKey: "sk-openai-demo",
      active: true,
      includeInMulti: false,
    },
  ],
  multiResponseEnabled: false,
  systemPrompt: "Ты помогаешь автору Telegram-канала о личных финансах...",
};

export const initialTelegramProfileConfig: TelegramProfileConfig = {
  authStatus: "connected",
  authStep: "connected",
  apiId: "20483651",
  apiHash: "a4c9f2b71e6d48c0a93f5b2d8e17c064",
  phone: "+7 999 123-45-67",
  sessionName: "author-main.session",
  channel: "@demochannel",
  channelTitle: "Демо канал",
  channelStatus: "connected",
  syncMode: "history-and-live",
  lastSync: "2026-06-16T12:40:00.000Z",
  importedPosts: 128,
  botApiToken: "7123456789:AAHdemoOmniBotTokenForTGPlatform",
  botStatus: "idle",
  botUsername: "",
  botLastActivity: "—",
  botMessageCount: 0,
};

export const initialPinnedPostIds: string[] = ["1", "2"];

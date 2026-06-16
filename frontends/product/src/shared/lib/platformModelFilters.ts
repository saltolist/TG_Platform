export type ModelTypeId =
  | "llm"
  | "web"
  | "vision"
  | "imageGeneration"
  | "orchestrator"
  | "webReasoner"
  | "ragReasoner";
export type ModelFilterId = "all" | ModelTypeId;

export const PLATFORM_MODEL_TYPE_OPTIONS: { id: ModelTypeId; label: string; hint: string }[] = [
  { id: "llm", label: "LLM", hint: "генерация ответов и постов" },
  { id: "web", label: "Web Search", hint: "поиск и сбор источников" },
  { id: "vision", label: "Компьютерное зрение", hint: "анализ изображений и видео" },
  { id: "imageGeneration", label: "Генерация изображений", hint: "создание иллюстраций и обложек" },
  { id: "orchestrator", label: "Оркестратор", hint: "маршрутизация сценариев" },
  { id: "webReasoner", label: "Web Reasoner", hint: "рассуждения поверх web-источников" },
  { id: "ragReasoner", label: "RAG Reasoner", hint: "рассуждения поверх базы знаний" },
];

export const PLATFORM_MODEL_FILTERS: { id: ModelFilterId; label: string; hint: string }[] = [
  { id: "all", label: "Все", hint: "сравнение по типам моделей" },
  ...PLATFORM_MODEL_TYPE_OPTIONS,
];

# TG Platform — документация

**TG Platform** — CMS для Telegram-каналов с AI-ассистентом.  
Платформа позволяет авторам планировать, создавать и анализировать публикации, вести AI-диалоги в контексте постов и глобально, управлять заметками и отслеживать аналитику канала.

---

## Содержание

### 👤 Для пользователей
| Раздел | Описание |
|--------|----------|
| [Начало работы](user/onboarding.md) | Регистрация, первый запуск, базовый сценарий |
| [Лента и посты](user/features/feed.md) | Драфты, публикации, планирование |
| [Редактор (Composer)](user/features/composer.md) | Создание постов, вложения, AI-генерация |
| [Чаты](user/features/chats.md) | Глобальные чаты и чаты к постам |
| [Заметки](user/features/notes.md) | Глобальные заметки и заметки к постам |
| [Аналитика](user/features/analytics.md) | Топ-посты, просмотры, реакции |
| [Настройки](user/features/settings.md) | Профиль канала, AI-модели, Telegram |
| [FAQ](user/faq.md) | Частые вопросы |

### 🛠 Для разработчиков
| Раздел | Описание |
|--------|----------|
| [Старт проекта](dev/setup.md) | Установка, запуск, переменные окружения |
| [Архитектура](dev/architecture.md) | FSD, слои, паттерны, потоки данных |
| [API-контракты](dev/api-contracts.md) | Эндпоинты, Zod-схемы, типы |
| [Тестирование](dev/testing.md) | Стратегия, инструменты, примеры |
| [Деплой / CI/CD](dev/deploy.md) | Сборка, окружения, публикация |
| [ADR — решения](dev/adr/README.md) | Зафиксированные архитектурные решения |

### 🔌 Backend
| Раздел | Описание |
|--------|----------|
| [Roadmap](backend/roadmap.md) | Фазы, приоритеты, план реализации |
| [Эндпоинты](backend/endpoints.md) | Полный список API с методами и схемами |
| [OpenAPI](backend/openapi.md) | OpenAPI 3.1 спецификация |

---

## Стек технологий

| Категория | Технология |
|-----------|-----------|
| Framework | Next.js 16 (App Router) |
| UI | React 19, Tailwind CSS v4, shadcn v4 |
| Server state | TanStack Query v5 |
| UI state | Zustand v5 |
| Validation | Zod v4 |
| Mock API | MSW v2 |
| Testing | Vitest + Testing Library + Playwright |
| Language | TypeScript 5 (strict) |

## Архитектурный подход

Проект следует **Feature-Sliced Design (FSD)** — слоистой методологии, при которой каждый слой зависит только от нижележащих:

```
app → screens → widgets → features → entities → shared
```

Подробнее — в [архитектурном обзоре](dev/architecture.md).

## Быстрый старт

```bash
cd web
npm install
npm run dev        # http://localhost:3020
npm run typecheck  # проверка типов
npm run test       # юнит-тесты
```

> В dev-режиме используется MSW (Mock Service Worker) — бэкенд не нужен.

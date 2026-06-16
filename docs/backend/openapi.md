# OpenAPI 3.1 Спецификация

```yaml
openapi: "3.1.0"
info:
  title: TG Platform API
  version: "1.0.0"
  description: CMS для Telegram-каналов с AI-ассистентом

servers:
  - url: /api/v1
    description: API v1

components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT

  schemas:
    Error:
      type: object
      required: [error]
      properties:
        error:
          type: string

    PostStatus:
      type: string
      enum: [published, scheduled, draft]

    PostMedia:
      type: object
      required: [name, url, type]
      properties:
        name:
          type: string
        url:
          type: string
        type:
          type: string

    PostReaction:
      type: object
      required: [emoji, count]
      properties:
        emoji:
          type: string
        count:
          type: integer

    PostMetrics:
      type: object
      required: [views, reposts, reactions]
      properties:
        views:
          type: string
        reposts:
          type: integer
        reactions:
          type: array
          items:
            $ref: "#/components/schemas/PostReaction"

    NoteFile:
      type: object
      required: [name, type]
      properties:
        id:
          type: string
        name:
          type: string
        type:
          type: string
        url:
          type: string

    AiVariant:
      type: object
      required: [key, label, text]
      properties:
        key:
          type: string
        label:
          type: string
        text:
          type: string
        llmCaption:
          type: string
        webCaption:
          type: string

    ChatMessage:
      type: object
      required: [role]
      properties:
        role:
          type: string
          enum: [user, ai]
        text:
          type: string
        variants:
          type: array
          items:
            $ref: "#/components/schemas/AiVariant"
        selectedVariant:
          type: integer
        mode:
          type: string
          enum: [single, multi]
        targetLabel:
          type: string
        llmLabel:
          type: string
        webLabel:
          type: string

    LocalNote:
      type: object
      required: [id, title, date, ai, body]
      properties:
        id:
          type: string
          format: uuid
        title:
          type: string
        date:
          type: string
          format: date-time
        ai:
          type: boolean
        body:
          type: string
        files:
          type: array
          items:
            $ref: "#/components/schemas/NoteFile"

    LocalChat:
      type: object
      required: [id, title, preview, date, history, ai]
      properties:
        id:
          type: string
          format: uuid
        title:
          type: string
        preview:
          type: string
        date:
          type: string
          format: date-time
        history:
          type: array
          items:
            $ref: "#/components/schemas/ChatMessage"
        ai:
          type: boolean

    PostComment:
      type: object
      required: [id, author, text, date]
      properties:
        id:
          type: string
          format: uuid
        author:
          type: string
        text:
          type: string
        date:
          type: string
          format: date-time
        replyToId:
          type: string
          format: uuid
        media:
          type: array
          items:
            $ref: "#/components/schemas/PostMedia"

    Post:
      type: object
      required: [id, status, rubric, text, notes, chats]
      properties:
        id:
          type: string
          format: uuid
        status:
          $ref: "#/components/schemas/PostStatus"
        date:
          type: string
          format: date-time
        created:
          type: string
          format: date-time
        rubric:
          type: string
          nullable: true
        metrics:
          $ref: "#/components/schemas/PostMetrics"
        text:
          type: string
        media:
          type: array
          items:
            $ref: "#/components/schemas/PostMedia"
        notes:
          type: array
          items:
            $ref: "#/components/schemas/LocalNote"
        chats:
          type: array
          items:
            $ref: "#/components/schemas/LocalChat"
        comments:
          type: array
          items:
            $ref: "#/components/schemas/PostComment"

    GlobalChat:
      type: object
      required: [id, title, preview, date, history]
      properties:
        id:
          type: string
          format: uuid
        kind:
          type: string
          enum: [default, omnichannel]
        title:
          type: string
        preview:
          type: string
        date:
          type: string
          format: date-time
        history:
          type: array
          items:
            $ref: "#/components/schemas/ChatMessage"

    GlobalNote:
      type: object
      required: [id, title, ai, date, body]
      properties:
        id:
          type: string
          format: uuid
        title:
          type: string
        ai:
          type: boolean
        date:
          type: string
          format: date-time
        body:
          type: string
        files:
          type: array
          items:
            $ref: "#/components/schemas/NoteFile"

    ChannelProfileRubric:
      type: object
      required: [id, title, description]
      properties:
        id:
          type: string
        title:
          type: string
        description:
          type: string

    ChannelProfileConfig:
      type: object
      properties:
        core:
          type: object
          properties:
            topic: { type: string }
            audience: { type: string }
            promise: { type: string }
            angle: { type: string }
            author: { type: string }
        voice:
          type: object
          properties:
            tone: { type: string }
            format: { type: string }
            phrases: { type: string }
        rules:
          type: object
          properties:
            must: { type: string }
            avoid: { type: string }
        rubrics:
          type: array
          items:
            $ref: "#/components/schemas/ChannelProfileRubric"

    LlmModel:
      type: object
      required: [id, provider, model, apiKey, active, includeInMulti]
      properties:
        id: { type: string }
        provider: { type: string }
        model: { type: string }
        apiKey: { type: string }
        active: { type: boolean }
        includeInMulti: { type: boolean }

    AiProfileConfig:
      type: object
      properties:
        llmModels:
          type: array
          items: { $ref: "#/components/schemas/LlmModel" }
        webSearchModels:
          type: array
          items: { $ref: "#/components/schemas/LlmModel" }
        visionModels:
          type: array
          items: { $ref: "#/components/schemas/LlmModel" }
        imageGenerationModels:
          type: array
          items: { $ref: "#/components/schemas/LlmModel" }
        orchestratorModels:
          type: array
          items: { $ref: "#/components/schemas/LlmModel" }
        webReasonerModels:
          type: array
          items: { $ref: "#/components/schemas/LlmModel" }
        ragReasonerModels:
          type: array
          items: { $ref: "#/components/schemas/LlmModel" }
        multiResponseEnabled: { type: boolean }
        systemPrompt: { type: string }

    TelegramProfileConfig:
      type: object
      properties:
        authStatus:
          type: string
          enum: [idle, code-sent, authorized, connected]
        authStep: { type: string }
        apiId: { type: string }
        apiHash: { type: string }
        phone: { type: string }
        sessionName: { type: string }
        channel: { type: string }
        channelTitle: { type: string }
        channelStatus:
          type: string
          enum: [idle, pending, connected]
        syncMode:
          type: string
          enum: [live-only, history-and-live, publish-only]
        lastSync:
          type: string
          format: date-time
        importedPosts: { type: integer }
        botApiToken: { type: string }
        botStatus:
          type: string
          enum: [idle, connected]
        botUsername: { type: string }
        botLastActivity:
          type: string
          format: date-time
        botMessageCount: { type: integer }

security:
  - bearerAuth: []

paths:
  /auth/register:
    post:
      tags: [Auth]
      security: []
      summary: Регистрация
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [email, password]
              properties:
                email: { type: string, format: email }
                password: { type: string }
      responses:
        "200":
          description: Успешная регистрация
          content:
            application/json:
              schema:
                type: object
                properties:
                  token: { type: string }
                  userId: { type: string }

  /auth/login:
    post:
      tags: [Auth]
      security: []
      summary: Вход
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [email, password]
              properties:
                email: { type: string, format: email }
                password: { type: string }
      responses:
        "200":
          description: Успешный вход
          content:
            application/json:
              schema:
                type: object
                properties:
                  token: { type: string }
                  userId: { type: string }
        "401":
          description: Неверные credentials
          content:
            application/json:
              schema: { $ref: "#/components/schemas/Error" }

  /auth/logout:
    post:
      tags: [Auth]
      summary: Выход
      responses:
        "204":
          description: Успешный выход

  /posts:
    get:
      tags: [Posts]
      summary: Список постов
      responses:
        "200":
          description: Список постов
          content:
            application/json:
              schema:
                type: array
                items: { $ref: "#/components/schemas/Post" }
    post:
      tags: [Posts]
      summary: Создать пост
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: "#/components/schemas/Post" }
      responses:
        "201":
          description: Пост создан
          content:
            application/json:
              schema: { $ref: "#/components/schemas/Post" }

  /posts/reorder:
    put:
      tags: [Posts]
      summary: Изменить порядок постов
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                posts:
                  type: array
                  items: { $ref: "#/components/schemas/Post" }
      responses:
        "200":
          description: Обновлённый список
          content:
            application/json:
              schema:
                type: array
                items: { $ref: "#/components/schemas/Post" }

  /posts/{id}:
    patch:
      tags: [Posts]
      summary: Обновить пост
      parameters:
        - in: path
          name: id
          required: true
          schema: { type: string, format: uuid }
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: "#/components/schemas/Post" }
      responses:
        "200":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/Post" }
        "404":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/Error" }
    delete:
      tags: [Posts]
      summary: Удалить пост
      parameters:
        - in: path
          name: id
          required: true
          schema: { type: string, format: uuid }
      responses:
        "204":
          description: Удалён
        "404":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/Error" }

  /global-chats:
    get:
      tags: [GlobalChats]
      summary: Список чатов
      responses:
        "200":
          content:
            application/json:
              schema:
                type: array
                items: { $ref: "#/components/schemas/GlobalChat" }
    post:
      tags: [GlobalChats]
      summary: Создать чат
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: "#/components/schemas/GlobalChat" }
      responses:
        "201":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/GlobalChat" }

  /global-chats/{chatId}/messages:
    post:
      tags: [GlobalChats]
      summary: Добавить сообщение и получить AI-ответ
      parameters:
        - in: path
          name: chatId
          required: true
          schema: { type: string, format: uuid }
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [text]
              properties:
                text: { type: string }
      responses:
        "200":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/GlobalChat" }

  /global-chats/{chatId}:
    patch:
      tags: [GlobalChats]
      summary: Обновить чат
      parameters:
        - in: path
          name: chatId
          required: true
          schema: { type: string, format: uuid }
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: "#/components/schemas/GlobalChat" }
      responses:
        "200":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/GlobalChat" }
    delete:
      tags: [GlobalChats]
      summary: Удалить чат
      parameters:
        - in: path
          name: chatId
          required: true
          schema: { type: string, format: uuid }
      responses:
        "204":
          description: Удалён

  /global-notes:
    get:
      tags: [GlobalNotes]
      summary: Список заметок
      responses:
        "200":
          content:
            application/json:
              schema:
                type: array
                items: { $ref: "#/components/schemas/GlobalNote" }

  /global-notes/{noteId}:
    put:
      tags: [GlobalNotes]
      summary: Создать или обновить заметку
      parameters:
        - in: path
          name: noteId
          required: true
          schema: { type: string, format: uuid }
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: "#/components/schemas/GlobalNote" }
      responses:
        "200":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/GlobalNote" }
    delete:
      tags: [GlobalNotes]
      summary: Удалить заметку
      parameters:
        - in: path
          name: noteId
          required: true
          schema: { type: string, format: uuid }
      responses:
        "204":
          description: Удалена

  /profile/channel:
    get:
      tags: [Profile]
      summary: Профиль канала
      responses:
        "200":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/ChannelProfileConfig" }
    put:
      tags: [Profile]
      summary: Обновить профиль канала
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: "#/components/schemas/ChannelProfileConfig" }
      responses:
        "200":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/ChannelProfileConfig" }

  /profile/ai:
    get:
      tags: [Profile]
      summary: AI-настройки
      responses:
        "200":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/AiProfileConfig" }
    put:
      tags: [Profile]
      summary: Обновить AI-настройки
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: "#/components/schemas/AiProfileConfig" }
      responses:
        "200":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/AiProfileConfig" }

  /profile/telegram:
    get:
      tags: [Profile]
      summary: Telegram-настройки
      responses:
        "200":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/TelegramProfileConfig" }
    put:
      tags: [Profile]
      summary: Обновить Telegram-настройки
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: "#/components/schemas/TelegramProfileConfig" }
      responses:
        "200":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/TelegramProfileConfig" }

  /ai/reply:
    post:
      tags: [AI]
      summary: Получить ответ AI-ассистента
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [text, scope]
              properties:
                text: { type: string }
                scope:
                  type: string
                  enum: [global, post]
      responses:
        "200":
          content:
            application/json:
              schema:
                type: object
                required: [text]
                properties:
                  text: { type: string }
```

← [Назад к backend](README.md)

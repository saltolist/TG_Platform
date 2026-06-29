# Окна LLM для сценария post-чата (метки `msg-ver-branch`)

> Сценарий: таблица событий post-чата (ветки 1–6, сообщения 1–14).  
> Формат метки: `{msg}-{msgVersion}-{branch}` (колонка K таблицы).  
> Сводки: `head` / `attach` по каналу и посту — в JSON (`contextStamp`), не в строке метки.

**Параметры сборки (как в коде):**

- `PROMPT_WINDOW = 5` — в диалог попадают последние 5 пар user/assistant на **активной ветке**.
- Primer: `SUMMARY_BUNDLE` по **head** (канал + пост) + при длинной истории блок «Сводка по диалогу».
- Float: блок «Обновлённый профиль канала» / «Обновлённый пост» вшивается в **user-turn** с ненулевым attach.
- События без отправки сообщения (правка каталога, переключение ветки) — **нет вызова LLM**, в файле пропущены.

**Условные обозначения:**

- `uN` / `aN` — текст N-го user-/assistant-сообщения на **текущей ветке**.
- `…канал vN…` / `…пост vN…` — текст bundle из каталога версии N.
- `[метка]` — `contextLabel` на user-turn.
- Ответ AI — то, что модель генерирует **после** этого запроса (следующее assistant-сообщение на ветке).

---

## Ветка 1

### Строка 3 — msg 1, метка `1-1-1`

| Head | Attach | Каталог |
|------|--------|---------|
| ch 5, post 2 | 0, 0 | ch 5, post 2 |

```
[0] system
    {systemPrompt + addendum post}

[1] user/primer  [head ch5 + post v2]
    Профиль канала:
    …канал v5…
    Пост:
    …пост v2…

[2] assistant/primer-ack
    Понял, учту при ответах.

[3] user  [1-1-1]
    u1
```

**Ответ AI:** `a1`

---

### Строка 4 — msg 2, метка `2-1-1`

| Head | Attach |
|------|--------|
| ch 5, post 2 | 0, 0 |

```
[0] system
    …

[1] user/primer  [head ch5 + post v2]
    …

[2] assistant/primer-ack
    Понял, учту при ответах.

[3] user  [1-1-1]
    u1

[4] assistant
    a1

[5] user  [2-1-1]
    u2
```

**Ответ AI:** `a2`

---

### Строка 6 — msg 3, метка `3-1-1`

| Head | Attach |
|------|--------|
| ch 5, post 2 | 0, **post 3** |

*(между строками 5–6: в каталоге появился пост v3)*

```
[0] system
    …

[1] user/primer  [head ch5 + post v2]   ← primer ещё старый пост
    Профиль канала: …канал v5…
    Пост: …пост v2…

[2] assistant/primer-ack
    …

[3] user  [1-1-1]
    u1
[4] assistant
    a1
[5] user  [2-1-1]
    u2
[6] assistant
    a2

[7] user/float-post  [3-1-1]
    Обновлённый пост:
    …пост v3…

    u3
```

**Ответ AI:** `a3`

---

### Строка 7 — msg 4, метка `4-1-1`

| Head | Attach |
|------|--------|
| ch 5, post 2 | 0, 0 |

```
[0] system …
[1] user/primer  [head ch5 + post v2]
[2] assistant/primer-ack …

[3] user  [1-1-1]  u1
[4] assistant  a1
[5] user  [2-1-1]  u2
[6] assistant  a2
[7] user  [3-1-1]  u3          ← float v3 уже был на turn 3, не повторяется
[8] assistant  a3

[9] user  [4-1-1]
    u4
```

**Ответ AI:** `a4`

---

### Строка 9 — msg 5, метка `5-1-1`

| Head | Attach |
|------|--------|
| ch 5, post 2 | **ch 6**, 0 |

```
[0] system …
[1] user/primer  [head ch5 + post v2]
[2] assistant/primer-ack …

[3] user  [1-1-1]  u1
[4] assistant  a1
[5] user  [2-1-1]  u2
[6] assistant  a2
[7] user  [3-1-1]  u3
[8] assistant  a3
[9] user  [4-1-1]  u4
[10] assistant  a4

[11] user/float-channel  [5-1-1]
     Обновлённый профиль канала:
     …канал v6…

     u5
```

**Ответ AI:** `a5` *(после него — edit → ветка 2)*

---

### Строка 21 — msg 6, метка `6-1-1` *(после возврата на ветку 1, строка 20)*

| Head | Attach |
|------|--------|
| ch 5, post **3** | **ch 8**, **post 6** |

*(на ветке 1 local head дозрел до post v3; в каталоге ch 8, post 6)*

```
[0] system …

[1] user/primer  [head ch5 + post v3]
    Профиль канала: …канал v5…
    Пост: …пост v3…

[2] assistant/primer-ack …

    (окно: последние 5 пар на ветке 1 — u1…u5 v1)

[3] user  [1-1-1]  u1
[4] assistant  a1
[5] user  [2-1-1]  u2
[6] assistant  a2
[7] user  [3-1-1]  u3
[8] assistant  a3
[9] user  [4-1-1]  u4
[10] assistant  a4
[11] user  [5-1-1]  u5 (версия 1)
[12] assistant  a5

[13] user/float-channel+post  [6-1-1]
     Обновлённый профиль канала: …канал v8…
     Обновлённый пост: …пост v6…

     u6
```

**Ответ AI:** `a6`

---

### Строка 22 — msg 7, метка `7-1-1`

| Head | Attach |
|------|--------|
| ch 5, post 3 | 0, 0 |

```
[1] user/primer  [head ch5 + post v3]
…
(окно: u2…u6)

[user 2-1-1] u2 … [user 6-1-1] u6 [asst] a6
[user 7-1-1] u7
```

**Ответ AI:** `a7`

---

### Строка 23 — msg 8, метка `8-1-1`

| Head | Attach |
|------|--------|
| ch **6**, post 3 | 0, 0 |

*(догоняние: post v3 созрел в head на turn 8; global ch 6 — по очереди pending)*

```
[1] user/primer  [head ch6 + post v3]
    …канал v6…  …пост v3…

(окно: u3…u7)

[user 7-1-1] u7 [asst] a7
[user 8-1-1] u8
```

**Ответ AI:** `a8`

---

### Строка 25 — msg 9, метка `9-1-1`

| Head | Attach |
|------|--------|
| ch **8**, post **6** | 0, **post 7** |

```
[1] user/primer  [head ch8 + post v6]

(окно: u4…u8)

[user 8-1-1] u8 [asst] a8

[user/float-post 9-1-1]
 Обновлённый пост: …пост v7…
 u9
```

**Ответ AI:** `a9`

---

### Строка 26 — msg 10, метка `10-1-1`

| Head | Attach |
|------|--------|
| ch 8, post 6 | 0, 0 |

```
[1] user/primer  [head ch8 + post v6]

(окно: u5…u9)

[user 9-1-1] u9 [asst] a9
[user 10-1-1] u10
```

**Ответ AI:** `a10` *(далее edit → ветка 3)*

---

## Ветка 2

### Строка 10 — edit msg 5, метка `5-2-2`

| Head | Attach |
|------|--------|
| ch 5, post 2 | ch 6, 0 |

*(регенерация на отредактированном u5, ветка 2)*

```
[1] user/primer  [head ch5 + post v2]

[3] user  [1-1-1]  u1
…
[9] user  [4-1-1]  u4
[10] assistant  a4

[11] user/float-channel  [5-2-2]
     Обновлённый профиль канала: …канал v6…
     u5 (версия 2, ветка 2)
```

**Ответ AI:** `a5'` *(новый ответ на ветке 2)*

---

### Строка 11 — msg 6, метка `6-1-2`

| Head | Attach |
|------|--------|
| ch 5, post **3** | 0, 0 |

*(на ветке 2 local head дозрел до post v3 после fork)*

```
[1] user/primer  [head ch5 + post v3]

(окно: u1…u5 v2 — 5 пар)

[user 5-2-2] u5' [asst] a5'
[user 6-1-2] u6
```

**Ответ AI:** `a6`

---

### Строка 13 — msg 7, метка `7-1-2`

| Head | Attach |
|------|--------|
| ch 5, post 3 | **ch 7**, **post 4** |

```
[1] user/primer  [head ch5 + post v3]

[user 5-2-2] u5' … [user 6-1-2] u6 [asst] a6

[user/float-channel+post 7-1-2]
 Обновлённый профиль канала: …канал v7…
 Обновлённый пост: …пост v4…
 u7
```

**Ответ AI:** `a7`

---

### Строка 16 — msg 8, метка `8-1-2`

| Head | Attach |
|------|--------|
| ch **6**, post 3 | 0, **post 6** |

```
[1] user/primer  [head ch6 + post v3]

(окно: u4…u7 на ветке 2)

[user 7-1-2] u7 [asst] a7

[user/float-post 8-1-2]
 Обновлённый пост: …пост v6…
 u8
```

**Ответ AI:** `a8`

---

### Строка 17 — msg 9, метка `9-1-2`

| Head | Attach |
|------|--------|
| ch 6, post 3 | 0, 0 |

```
[1] user/primer  [head ch6 + post v3]
…
[user 8-1-2] u8 [asst] a8
[user 9-1-2] u9
```

**Ответ AI:** `a9`

---

### Строка 19 — msg 10, метка `10-1-2`

| Head | Attach |
|------|--------|
| ch **7**, post **4** | **ch 8**, 0 |

```
[1] user/primer  [head ch7 + post v4]

(окно: u5…u9)

[user 9-1-2] u9 [asst] a9

[user/float-channel 10-1-2]
 Обновлённый профиль канала: …канал v8…
 u10
```

**Ответ AI:** `a10`

---

## Ветка 3

### Строка 28 — edit msg 10, метка `10-2-3`

| Head | Attach |
|------|--------|
| ch 8, post 6 | **ch 9**, **post 8** |

```
[1] user/primer  [head ch8 + post v6]

(хвост ветки 3 от u10 v2)

… u9 [asst] a9
[user/float-channel+post 10-2-3]
 Обновлённый профиль канала: …канал v9…
 Обновлённый пост: …пост v8…
 u10 (версия 2)
```

**Ответ AI:** `a10'`

---

### Строка 29 — msg 11, метка `11-1-3`

| Head | Attach |
|------|--------|
| ch 8, post 6 | 0, 0 |

```
[1] user/primer  [head ch8 + post v6]

[user 10-2-3] u10' [asst] a10'
[user 11-1-3] u11
```

**Ответ AI:** `a11`

---

### Строка 30 — msg 12, метка `12-1-3`

| Head | Attach |
|------|--------|
| ch 8, post **7** | 0, 0 |

```
[1] user/primer  [head ch8 + post v7]
…
[user 11-1-3] u11 [asst] a11
[user 12-1-3] u12
```

**Ответ AI:** `a12`

---

### Строка 31 — msg 13, метка `13-1-3`

| Head | Attach |
|------|--------|
| ch **9**, post **8** | 0, 0 |

```
[1] user/primer  [head ch9 + post v8]
…
[user 12-1-3] u12 [asst] a12
[user 13-1-3] u13
```

**Ответ AI:** `a13`

---

### Строка 33 — msg 14, метка `14-1-3`

| Head | Attach |
|------|--------|
| ch 9, post 8 | 0, **post 9** |

```
[1] user/primer  [head ch9 + post v8]

(окно: u10…u13)

[user 13-1-3] u13 [asst] a13

[user/float-post 14-1-3]
 Обновлённый пост: …пост v9…
 u14
```

**Ответ AI:** `a14`

---

## Ветка 4

### Строка 34 — edit msg 10, метка `10-3-4`

| Head | Attach |
|------|--------|
| ch 8, post 6 | **ch 9**, **post 9** |

```
[1] user/primer  [head ch8 + post v6]

[user/float-channel+post 10-3-4]
 Обновлённый профиль канала: …канал v9…
 Обновлённый пост: …пост v9…
 u10 (версия 3, ветка 4)
```

**Ответ AI:** `a10''`

---

### Строка 36 — msg 11, метка `11-1-4`

| Head | Attach |
|------|--------|
| ch 8, post 6 | 0, **post 10** |

```
[1] user/primer  [head ch8 + post v6]

[user 10-3-4] u10'' [asst] a10''

[user/float-post 11-1-4]
 Обновлённый пост: …пост v10…
 u11
```

**Ответ AI:** `a11`

---

### Строка 37 — msg 12, метка `12-1-4`

| Head | Attach |
|------|--------|
| ch 8, post **7** | 0, 0 |

```
[1] user/primer  [head ch8 + post v7]
…
[user 11-1-4] u11 [asst] a11
[user 12-1-4] u12
```

**Ответ AI:** `a12`

---

## Ветка 5

### Строка 40 — edit msg 11, метка `11-2-5`

| Head | Attach |
|------|--------|
| ch 8, post 6 | 0, **post 11** |

```
[1] user/primer  [head ch8 + post v6]

[user/float-post 11-2-5]
 Обновлённый пост: …пост v11…
 u11 (версия 2, ветка 5)
```

**Ответ AI:** `a11'`

---

### Строка 41 — msg 12, метка `12-1-5`

| Head | Attach |
|------|--------|
| ch 8, post **7** | 0, 0 |

```
[1] user/primer  [head ch8 + post v7]
[user 11-2-5] u11' [asst] a11'
[user 12-1-5] u12
```

**Ответ AI:** `a12`

---

### Строка 42 — msg 13, метка `13-1-5`

| Head | Attach |
|------|--------|
| ch **9**, post **9** | 0, 0 |

```
[1] user/primer  [head ch9 + post v9]
…
[user 12-1-5] u12 [asst] a12
[user 13-1-5] u13
```

**Ответ AI:** `a13`

---

## Ветка 6 *(retroactive fork от msg 3)*

### Строка 43 — edit msg 3, метка `3-2-6`

| Head | Attach |
|------|--------|
| ch 5, post 2 | **ch 9**, **post 11** |

```
[1] user/primer  [head ch5 + post v2]

[u1] [a1] [u2] [a2]

[user/float-channel+post 3-2-6]
 Обновлённый профиль канала: …канал v9…
 Обновлённый пост: …пост v11…
 u3 (версия 2, ветка 6)
```

**Ответ AI:** `a3'`

---

### Строка 44 — msg 4, метка `4-1-6`

| Head | Attach |
|------|--------|
| ch 5, post 2 | 0, 0 |

```
[1] user/primer  [head ch5 + post v2]
[user 3-2-6] u3' [asst] a3'
[user 4-1-6] u4
```

**Ответ AI:** `a4`

---

### Строка 48 — msg 5, метка `5-1-6`

| Head | Attach |
|------|--------|
| ch 5, post 2 | **ch 11**, **post 13** |

```
[1] user/primer  [head ch5 + post v2]

(окно: u1…u4 на ветке 6)

[user/float-channel+post 5-1-6]
 Обновлённый профиль канала: …канал v11…
 Обновлённый пост: …пост v13…
 u5
```

**Ответ AI:** `a5`

---

### Строка 49 — msg 6, метка `6-1-6`

| Head | Attach |
|------|--------|
| ch **9**, post **11** | 0, 0 |

```
[1] user/primer  [head ch9 + post v11]
    (head догнал pending после float на turn 5)

[user 5-1-6] u5 [asst] a5
[user 6-1-6] u6
```

**Ответ AI:** `a6`

---

### Строка 51 — msg 7, метка `7-1-6`

| Head | Attach |
|------|--------|
| ch 9, post 11 | **ch 12**, 0 |

```
[1] user/primer  [head ch9 + post v11]

[user 5-1-6] u5 … [user 6-1-6] u6 [asst] a6

[user/float-channel 7-1-6]
 Обновлённый профиль канала: …канал v12…
 u7
```

**Ответ AI:** `a7`

---

## Пропущенные строки (нет окна LLM)

| Строка | Событие |
|--------|---------|
| 5, 8, 12, 14–15, 18 | обновление каталога (канал/пост) |
| 20, 39 | переключение активной ветки в UI |
| 24, 27, 32, 35, 38, 45–47, 50 | только каталог, без сообщения |

---

## Пример `contextStamp` + метка (строка 6)

**Метка:** `3-1-1`

```json
{
  "contextLabel": "3-1-1",
  "contextStamp": {
    "address": { "msg": 3, "msgVersion": 1, "branch": 1 },
    "summary": {
      "head": { "channel": 5, "post": 2 },
      "attach": { "channel": 0, "post": 3 }
    },
    "catalog": { "channel": 5, "post": 3 }
  }
}
```

---

## Заметки для golden-теста

1. **Primer head** берётся из `contextStamp.summary.head`, не из актуального каталога B/C.
2. **Float** только на turn с ненулевым `attach`; повторно на том же turn не дублируется.
3. **Окно** — последние 5 пар; при msg > 5 ранние пары уходят из диалога (в rolling summary, если история длиннее `HISTORY_WINDOW`).
4. **Ветки изолированы**: на ветке 2 в окне нет `u5` версии 1 с ветки 1 — только `u5'` (`5-2-2`).
5. Строки таблицы с **догонянием** head без msg — вынести отдельными событиями между сообщениями (см. обсуждение сценария); в этом файле догоняние отражено сменой head в primer на **следующем** msg.

← [Метки сводок](summary-version-labels.md) · [Сборка контекста](ai-context-assembly.md)

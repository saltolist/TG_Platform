# BYOK Security — Runbook

Операционное руководство по безопасному управлению `BYOK_ENCRYPTION_KEY` —
Fernet-ключом, которым шифруются BYOK API-ключи и Telegram-секреты в таблице `profiles`.

---

## Что шифруется

| Таблица | Поле | Что внутри |
|---------|------|-----------|
| `profiles.ai` | `llmModels[*].apiKey`, `webSearchModels[*].apiKey`, … | BYOK-ключи LLM-провайдеров |
| `profiles.telegram` | `apiHash`, `botApiToken`, `sessionString` | Telegram MTProto / Bot API секреты |

Значения хранятся с префиксом `enc:v1:`. Без `BYOK_ENCRYPTION_KEY` они **нерасшифруемы**.

---

## Генерация ключа

```bash
# Из backend-окружения:
.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Или в Docker:
docker compose exec backend python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Результат — строка вида `ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=`.

---

## Бэкап ключа

> **Потеря ключа = безвозвратная потеря всех BYOK и Telegram-секретов в БД.**

Рекомендуемые места хранения (в порядке предпочтения):

1. **Password manager** (1Password, Bitwarden) — отдельная запись «TG Platform BYOK key (prod)».
2. **CI/CD secrets** (GitHub Actions → Settings → Secrets) — хранится отдельно от кода.
3. **Encrypted offline backup** — `BYOK_ENCRYPTION_KEY=…` в зашифрованном архиве (GPG).

**Не храните ключ:**
- в `.env` файлах, которые могут попасть в git.
- в README или документации в открытом виде.
- в одном месте без копии.

### Проверка бэкапа

Периодически убеждайтесь, что сохранённый ключ расшифровывает реальное значение:

```bash
# Взять любое enc:v1: значение из БД:
docker compose exec postgres psql -U tg -d tg \
  -c "SELECT ai->>'llmModels' FROM profiles LIMIT 1;"

# Расшифровать вручную:
python - <<'EOF'
from cryptography.fernet import Fernet
key = b"<ваш_ключ>"
value = "<enc:v1:...значение...>"
f = Fernet(key)
print(f.decrypt(value.removeprefix("enc:v1:").encode()).decode())
EOF
```

---

## Ротация ключа

Используется, когда ключ мог быть скомпрометирован или истёк срок его действия.

### Шаги

1. **Сгенерируйте новый ключ** (см. выше).

2. **Обновите `.env` / secrets:**
   ```env
   BYOK_ENCRYPTION_KEY=<новый_ключ>
   BYOK_ENCRYPTION_OLD_KEYS=<старый_ключ>
   ```
   `BYOK_ENCRYPTION_OLD_KEYS` — список через запятую; нужен только для дешифровки старых значений.

3. **Запустите скрипт ротации:**
   ```bash
   # Сначала тестовый прогон (ничего не пишет в БД):
   python scripts/rotate_byok_key.py --dry-run

   # Применить:
   python scripts/rotate_byok_key.py
   ```
   Скрипт перешифрует все `enc:v1:` значения в `profiles.ai` и `profiles.telegram`
   новым первичным ключом.

4. **Убедитесь, что всё расшифровывается:**
   - Зайдите в UI → Профиль → проверьте, что AI-модели и Telegram-интеграция отображаются.
   - В логах бэкенда не должно быть `Failed to decrypt BYOK key`.

5. **Очистите старые ключи:**
   ```env
   BYOK_ENCRYPTION_OLD_KEYS=
   ```
   Перезапустите бэкенд.

6. **Обновите бэкап** новым ключом.

---

## KMS / Vault (prod-рекомендация)

Для production-окружений `BYOK_ENCRYPTION_KEY` лучше хранить не в `.env`,
а в выделенном менеджере секретов:

| Вариант | Как подключить |
|---------|---------------|
| **AWS Secrets Manager** | При старте контейнера вытаскивать значение через `aws secretsmanager get-secret-value` и записывать в env. |
| **HashiCorp Vault** | `vault kv get -field=value secret/tg-platform/byok-key` → env-переменная. |
| **Docker Swarm Secrets** | `docker secret create byok_key <file>` → монтировать как файл; читать в `config.py`. |
| **GitHub Actions** | `secrets.BYOK_ENCRYPTION_KEY` → передавать в `docker compose` через `--env`. |

Любой из этих вариантов гарантирует, что ключ **не хранится в репозитории**
и ротируется независимо от кода.

---

## Startup-guard

При старте бэкенд проверяет: если в БД есть значения с префиксом `enc:v1:`,
но `BYOK_ENCRYPTION_KEY` не задан — в лог пишется предупреждение:

```
WARNING tg.security: BYOK_ENCRYPTION_KEY is not set but N profile(s) contain
enc:v1: encrypted secrets.  These values CANNOT be decrypted until the key
is restored.  See docs/dev/security-byok.md.
```

Это **не останавливает** приложение (чтобы не блокировать разработку),
но сигнализирует о потенциальной потере данных.

---

## CSP (Content-Security-Policy)

Frontend использует **enforce** CSP для защиты от XSS (Docker / standalone).

| Контур | CSP |
|--------|-----|
| Docker / standalone | `frontend/src/proxy.ts` — `Content-Security-Policy` (enforce) |
| GitHub Pages / MSW | `layout.tsx` — permissive `<meta http-equiv="CSP">` |

Стратегия для Next.js SSG: `script-src 'self' 'unsafe-inline'` (nonce не работает
со статически пререндеренными страницами).

### Отчёты о нарушениях

CSP содержит `report-uri` → `POST /api/v1/csp-report/` на бэкенде.

Логи: `tg.security.csp` (уровень WARNING).

```bash
# Docker — смотреть отчёты в реальном времени:
docker compose logs -f backend | grep "CSP violation"
```

Эндпоинт без аутентификации — браузер шлёт отчёты автоматически.

### Проверка нарушений

Откройте браузер → DevTools → Console: ищите сообщения вида  
`Content Security Policy: The page's settings blocked the loading of a resource`.

Типичные нарушения и решения:

| Нарушение | Причина | Решение |
|-----------|---------|---------|
| `script-src` блокирует inline script | Inline `<script>` без nonce | Добавить `'unsafe-inline'` или перейти на dynamic SSR + nonce |
| `connect-src` блокирует запрос | Новый внешний API | Добавить домен в `connect-src` в `buildCsp()` |
| `img-src` блокирует изображение | Внешний CDN | Добавить домен в `img-src` |

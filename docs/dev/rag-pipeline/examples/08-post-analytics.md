# 08 — Post analytics

- Given: опубликованный пост с метриками.
- When: agent вызывает `GetPostAnalytics`.
- Then: числовые claims используют analytics evidence и сохраняют период.
- Reject: вычисленные показатели без исходных метрик.

# Hermes Knowledge Architecture — план интеграции

## Проблема

Сейчас знания размазаны:

| Где | Что | Проблема |
|-----|-----|----------|
| `~/wiki/` | 51 страница markdown | Плоский текст, нет перекрёстных связей |
| Hermes sessions | SQLite (state.db) | Только хронология, нет индекса по темам |
| Hermes memory | key-value факты | Только явные save, нет автоматических связей |
| hermes-orchestra | SQLite tasks | Только структурированные задачи |
| Tatneft audit logs | сырые логи | Нет извлечения знаний |
| Твоя голова | всё остальное | Самый узкий канал |

**Что хотим:** один запрос — и система собирает ответ из всех источников, проходя по связям.

---

## Архитектура

```
                    ┌──────────────────────────┐
                    │     Hermes Agent          │
                    │  (оркестратор + LLM)      │
                    └──────┬───────────────────┘
                           │
              ┌────────────┼────────────────┐
              ▼            ▼                ▼
     ┌────────────────┐ ┌──────────┐ ┌──────────────┐
     │  HippoRAG KG   │ │ LLM Wiki │ │ hermes-      │
     │  (граф знаний)  │ │ (md docs)│ │ orchestra    │
     │                │ │         │ │ (SQLite)     │
     │  триплеты из:   │ │ 51 стр  │ │ projects     │
     │  • wiki-страниц │ │ handoff │ │ tasks        │
     │  • сессий       │ │ рецепты │ │ статусы      │
     │  • Tatneft логов│ │ анти-   │ │ assignee     │
     │  • протоколов   │ │ паттерны│ │              │
     │  • findings     │ │         │ │              │
     └────────┬────────┘ └──────────┘ └──────────────┘
              │
              ▼
     ┌──────────────────────────────────────────────┐
     │         Hermes Memory (факты)                │
     │  user profile + preferences + stable facts   │
     └──────────────────────────────────────────────┘
```

**HippoRAG = мост между всеми источниками.** Он не заменяет ничего, а добавляет граф связей поверх.

---

## Роль HippoRAG

### 1. Препроцессор LLM Wiki

Текущая wiki: 51 markdown-страница, разбитая по папкам (`concepts/`, `entities/`, `troubleshooting/`).

**Сейчас:** чтобы найти "что мы знаем про prevlogin", ты открываешь файл или ищешь grep'ом. Связи между страницами — только ручные ссылки.

**С HippoRAG:** каждая страница → триплеты. Связи строятся автоматически:

```
Страница "concepts/aldpro-fly-wm-parsing-antipattern"
  → триплеты: (fly-wm, имеет, parsing-antipattern)
              (pam_kiosk2, не, pam_mount)
              (auth_report_pipe, парсит, format-6)

Страница "concepts/auth-report-pipe-v2"
  → триплеты: (DesktopP95, =, session_time - first_PAM)
              (DesktopP95, исключает, 0-значения)

PPR соединяет: fly-wm → auth_report_pipe → DesktopP95 → PAM
```

**Запрос:** `"как считается DesktopP95 и при чём тут fly-wm?"`
→ HippoRAG шагает: DesktopP95 → auth_report_pipe → fly-wm → pam_kiosk2
→ возвращает связный ответ из 3 страниц

### 2. Индексатор сессий Hermes

Каждая сессия Hermes содержит находки, ошибки, решения. Сейчас они лежат в state.db, доступны через `session_search`, но это текстовый поиск, не граф.

**С HippoRAG:** после каждой сессии — автоматическая индексация ключевых находок:

```
Сессия: "разбираем log01 audit pipeline"
  → триплеты: (log01, порт, 5114)
              (log01, формат, wrapped)
              (auth_report_pipe, запущен, log01)
              (digitaltn, шлёт, events.digitaltn.group:514)
```

**Запрос:** `"что у нас с digitaltn audit?"`
→ PPR: digitaltn → events.digitaltn.group → syslog-ng → log01:5114 → auth_report_pipe
→ Возвращает: схему pipeline, известные проблемы, статус

### 3. Knowledge layer для Tatneft

Tatneft — это сотни хостов, конфигураций, тикетов, логов. HippoRAG собирает всё в граф:

```
┌─────────────────────────────────────────────┐
│              Tatneft Knowledge Graph         │
│                                             │
│  log01 ──:5114── auth_report_pipe           │
│    │              │                         │
│   ans01       format-6 (wrapped)            │
│    │              │                         │
│  events.     PRESALE-9507                   │
│  digitaltn       │                          │
│    │          terraform/                    │
│   port 514      ansible/                    │
│                                             │
│  slow-login ── fly-dm ── pam_kiosk2 ──      │
│                  │                          │
│               pam_unix ── Desktop!          │
│                  │                          │
│               pam_mount (AFTER desktop)     │
└─────────────────────────────────────────────┘
```

**Запрос:** `"на каком хосте лежит auth_report_pipe и куда он пишет?"`
→ log01 → auth_report_pipe → (связанные находки)
→ Ответ: "log01.aldtn.lan (10.240.14.50:31003), пишет в ~/bin/, формат 6"

**Запрос:** `"почему на Tatneft login медленный, что мы уже проверили?"`
→ slow-login → fly-dm → pam_kiosk2 → "No profile found" WARNING
→ pam_mount → не блокирует десктоп
→ (связанные сессии + wiki-страницы + тикеты)

---

## Роль MemPalace

MemPalace — это MCP-сервер для графовой памяти (сущности + отношения). Он может быть **тонким слоем поверх HippoRAG** для:

1. **Структурированных сущностей** — хосты, люди, проекты, конфиги
2. **Точных отношений** — `log01 → managed_by → astra-adm`, `digitaltn → format → SLS`
3. **Таймлайнов событий** — когда что изменилось, кто что сказал

**HippoRAG vs MemPalace:**

| | HippoRAG | MemPalace |
|---|---|---|
| Тип | Документный граф (триплеты) | Сущностный граф (nodes + edges) |
| Индексация | Автоматическая (LLM извлекает триплеты) | Ручная или через MCP-тулы |
| Поиск | PPR по всему графу | Cypher / SPARQL запросы |
| Multi-hop | Есть, встроенный | Есть, через обход графа |
| LLM нужен | Да, для триплетов | Нет, если данные структурированы |
| Когда использовать | Тексты, документы, логи | Хосты, люди, конфиги, версии |

**Моя рекомендация:** MemPalace НЕ НУЖЕН, если:

1. HippoRAG стоит на VPS с LLM
2. Все сущности (хосты, люди) описываются в `org_structure.yaml` и wiki
3. Таймлайны идут в `task_events` (SQLite) или в HippoRAG как датированные триплеты

MemPalace имеет смысл, если нужно:
- Хранить топологию сети с точными версиями конфигов
- Делать Cypher-запросы: `MATCH (h:Host)-[:RUNS]->(s:Service) WHERE s.port=5114 RETURN h`
- Интегрироваться с чем-то, что уже использует Neo4j

Но для Tatneft-кейса HippoRAG покрывает 90% потребностей без дополнительных MCP-серверов.

---

## План внедрения

### Phase 1 — База (сразу при VPS)

```bash
# 1. Установка HippoRAG
pip install hipporag

# 2. Индексация wiki
find ~/wiki -name "*.md" -exec python -m tools.pipeline \
    --input {} --memory --json \; > /dev/null

# 3. Первый запрос
python -m tools.pipeline query "что мы знаем про audit pipeline?"
```

**Ожидаемый результат:** граф из 51 wiki-страницы + их связи.

### Phase 2 — Интеграция с Hermes

После каждой сессии — автоматический триплет в HippoRAG:

```python
# В конце сессии Hermes вызывает:
from tools.memory_indexer import index_document
index_document(
    text="Сессия от 2026-04-29: разбирали log01 audit pipeline. "
         "Выяснили: auth_report_pipe использует format 6, "
         "unwrap вложенного syslog. DesktopP95 = session_time - first_PAM.",
    doc_id="session-20260429-001"
)
```

Либо через tool: `/case10 run --input session.txt --memory`

### Phase 3 — Pre-query контекст

Перед началом сессии Hermes:

```
/case10 query "контекст: {текущая задача}"
```

Ответ HippoRAG → в system prompt как background context.

### Phase 4 — Автоматизация Tatneft

Каждый новый лог, конфиг, тикет — в HippoRAG:

```
log01: конфиг syslog-ng (2026-04-28)
  → триплеты: (log01, syslog-ng, порт 5114)
              (digitaltn, шлёт, events.digitaltn.group:514)
              (events.digitaltn.group, relay, log01:5114)

PRESALE-9507: terraform apply failed
  → триплеты: (PRESALE-9507, хост, log01)
              (PRESALE-9507, хост, ans01)
              (ans01, доступ, все хосты)
              (log01, пароль, отдельный от ans01)
```

---

## Что нужно для старта

| Компонент | Статус | Когда |
|-----------|--------|-------|
| VPS (4 vCPU, 6 GB) | В плане | — |
| HippoRAG | pip install | VPS ready |
| OPENROUTER_API_KEY | Есть? | сейчас |
| memory_indexer.py | ✅ Написан | сейчас |
| wiki pages (51 шт) | Существуют | сейчас |
| Hermes sessions | state.db | сейчас |

**Единственное, что нужно для запуска Phase 1:** VPS + `pip install hipporag` + настроить OpenRouter API key.

Хочешь, распишу Docker-композ для VPS со всеми сервисами сразу: HippoRAG, Hermes gateway, case10 pipeline, hermes-orchestra? Чтобы при получении VPS — поднять одной командой.

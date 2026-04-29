---
name: case10
description: "Кейс 10 — Формирование задач из неструктурированных данных. CPU-first: natasha NER + regex, LLM только как fallback."
version: "1.1.0"
tags: [case10, tasks, cpu, nlp, natasha, whisper]
requirements:
  - python>=3.10
  - faster-whisper
  - natasha
  - pyyaml
  - requests
env:
  - OPENROUTER_API_KEY (опционально, для LLM fallback)
  - JIRA_URL
  - JIRA_USERNAME
  - JIRA_API_TOKEN
  - TELEGRAM_BOT_TOKEN
  - TELEGRAM_CHAT_ID
---

# Case 10 — Формирование задач из неструктурированных данных

**CPU-first pipeline.** Никаких LLM для основной работы.

## Архитектура

```
Вход (текст/аудио/видео)
  │
  ├── STT: faster-whisper (CPU, int8)  ← если аудио/видео
  │
  └── Текст
        │
        ├── natasha NER (имена, даты, должности)
        ├── Regex-паттерны (5 типов конструкций)
        │
        ├── ✅ Найдено → валидация по оргструктуре → Jira → уведомления
        │
        └── ❌ Не найдено → LLM fallback (опционально, OpenRouter)
```

## Что работает на CPU (бесплатно)

| Компонент | Инструмент | RAM |
|-----------|-----------|-----|
| STT (речь в текст) | faster-whisper tiny | ~1 GB |
| Имена, даты, должности | natasha (BERing) | ~500 MB |
| Парсинг конструкций поручений | Regex (5 паттернов) | 0 |
| Валидация оргструктуры | BFS по графу | 0 |
| Jira / Confluence API | atlassian-python-api | 0 |
| Уведомления | HTTP / SMTP | 0 |

## Поддерживаемые паттерны

- `Сергей, подготовь тексты до четверга` — императив
- `Владимир, нужен доступ к серверу` — потребность
- `Сергей -> Дмитрий: подготовить отчёт` — стрелка
- `Иванову — сделать отчёт до 15.05` — дательный падеж
- `Иван — провести регрессионное тестирование` — тире

## Быстрый старт

```bash
pip install faster-whisper natasha pyyaml requests
python -m tools.pipeline --input sample.txt
python -m tools.pipeline --video meeting.mp4
python -m tools.pipeline --audio meeting.wav --json
```

## Команды навыка Hermes

- `/case10 run --input <file>` — полный pipeline
- `/case10 run --input <file> --memory` — pipeline + индексация в HippoRAG
- `/case10 run --video <file>` — со STT
- `/case10 query <вопрос>` — поиск по графу памяти HippoRAG
- `/case10 stats` — статистика памяти
- `/case10 reset` — сброс индекса
- `/case10 status` — проверить конфигурацию

## HippoRAG Memory

При запуске с `--memory` каждый документ индексируется в граф знаний.
HLlm извлекает триплеты, которые соединяются рёбрами по смыслу.
PPR (Personalized PageRank) позволяет находить связанные документы через 2-3 шага.

Запросы:
```bash
python -m tools.pipeline query "Что поручал Сергей?"
python -m tools.pipeline query "Какой статус по лендингу?"
python -m tools.pipeline stats
```

## Бюджет

LLM не нужен для основной работы. Если поднять VPS:

| Статья | Стоимость |
|--------|-----------|
| VPS 4 vCPU, 4 GB | 1 500–2 500 ₽/мес |
| LLM (опционально) | ~800 ₽/мес |

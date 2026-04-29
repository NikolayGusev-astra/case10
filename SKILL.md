---
name: case10
description: "Кейс 10 — Формирование задач из неструктурированных данных. Извлекает поручения из email, стенограмм встреч, протоколов и заметок, валидирует их по оргструктуре и создаёт задачи в Jira."
version: "1.0.0"
author: "Nous Research / Hermes Agent"
type: skill
tags:
  - case10
  - tasks
  - jira
  - confluence
  - unstructured-data
  - nlp
requirements:
  - python>=3.10
  - pyyaml
  - requests
  - atlassian-python-api
  - python-dotenv
env:
  - OPENROUTER_API_KEY
  - JIRA_URL
  - JIRA_USERNAME
  - JIRA_API_TOKEN
  - CONFLUENCE_URL
  - CONFLUENCE_USERNAME
  - CONFLUENCE_API_TOKEN
  - TELEGRAM_BOT_TOKEN
  - TELEGRAM_CHAT_ID
---

# Case 10 — Формирование задач из неструктурированных данных

## Описание

Полный pipeline для извлечения структурированных поручений из
неструктурированных источников с использованием Hermes Agent + OpenRouter.

**Входные источники:**
- Email (IMAP) — письма с поручениями
- Аудио/Видео встречи — VKS → DION → загрузка → STT (речь в текст)
- Существующие протоколы — DOCX/PDF/TXT
- Заметки — голосовые сообщения, текстовые заметки

**Обработка (Hermes Agent + OpenRouter):**
1. Извлечение текста (FFmpeg для аудио, прямой разбор для текста)
2. LLM-парсинг: извлечение кто → кому → что → срок → приоритет
3. Валидация по оргструктуре (MemPalace KG)
4. Создание задач в Jira / Linear
5. Страница протокола в Confluence
6. Call tracking + контроль
7. Уведомления через TG / MM / Email
8. Граф знаний (MemPalace / Neo4j)

**Правила валидации оргструктуры:**
- Руководитель → подчинённый: ✅ валидно, задача создаётся сразу
- Межфункциональное: ⚠️ требуется подтверждение, уведомление + запрос
- Подчинённый → руководитель: ❌ невалидно, заблокировано
- Нет полномочий: ❌ невалидно

## Быстрый старт

```bash
# 1. Установка
bash install.sh

# 2. Настройка окружения
cp config/.env.example .env
# отредактируйте .env — укажите API-ключи

# 3. Запуск с файлом
python -m tools.case10_pipeline --input sample.txt --org config/org_structure.yaml

# 4. Или через Hermes Agent
# Загрузите навык SKILL.md и выполните:
#   /case10 run --input <file>
```

## Команды навыка

- `/case10 run --input <file> [--model <model>]` — запустить полный pipeline
- `/case10 parse --input <file>` — только этап парсинга (без Jira/уведомлений)
- `/case10 validate --input <file>` — парсинг + валидация
- `/case10 status` — проверить статус конфигурации и соединений

## Структура репозитория

```
case10/
├── tools/
│   ├── __init__.py
│   ├── case10_pipeline.py   # Оркестратор pipeline
│   ├── org_validator.py     # Валидация оргструктуры
│   ├── jira_bridge.py       # Jira + Confluence API
│   └── notifier.py          # Уведомления (TG/MM/Email)
├── config/
│   ├── config.yaml          # Основная конфигурация
│   ├── org_structure.yaml   # Оргструктура (шаблон)
│   └── .env.example         # Переменные окружения
├── tests/
│   └── test_pipeline.py     # Тесты с mock-данными
├── SKILL.md                 # Описание навыка Hermes
├── install.sh               # Установщик
├── Makefile                 # Цели сборки/тестов
└── README.md                # Документация
```

## Пример входных данных

Поместите текст в файл (sample.txt):

```
Иванов -> Петров: подготовить отчёт по продажам за апрель до 15.05.

Поручение от Сергея Сидорова:
Ольге Васильевой — провести исследование рынка.
Срок: 20 мая, приоритет: высокий.

На совещании 28 апреля Елена Петрова поручила:
1. Ивану Кузнецову — обновить API документацию до 05.05.
2. Михаилу Фёдорову — исправить баг #452 на фронтенде, срочно.

Татьяна Морозова -> Алексей Волков: провести регрессионное тестирование модуля авторизации.
```

## Бюджет LLM

- Gemini 2.0 Flash: ~2500-3500 ₽/мес
- Nemotron Mini 4B (free): ~1500-2700 ₽/мес

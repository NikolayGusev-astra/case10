# Case 10 — Формирование задач из неструктурированных данных

**Hermes Agent pipeline** для автоматического извлечения поручений из email, стенограмм встреч, протоколов и заметок.

## Pipeline

```
Любой текст → LLM-парсинг → валидация по оргструктуре → Jira задачи →
Confluence протокол → уведомления TG/MM/Email
```

## Установка

```bash
git clone git@github.com:NikolayGusev-astra/case10.git
cd case10
bash install.sh
```

Или одной командой:

```bash
curl -fsSL https://raw.githubusercontent.com/NikolayGusev-astra/case10/main/install.sh | bash
```

## Быстрый старт

```bash
# 1. Настройка
cp config/.env.example .env
# отредактируйте .env — укажите API-ключи

# 2. Оргструктура
# отредактируйте config/org_structure.yaml — ваши сотрудники

# 3. Тест
make test

# 4. Запуск с файлом
cd case10 && source .venv/bin/activate
python -m tools.case10_pipeline --input sample.txt --org config/org_structure.yaml --config config/config.yaml
```

## Через Hermes Agent

```bash
hermes -s case10
```

В сессии:
```
/case10 run --input стенограмма.txt
/case10 parse --input письмо.txt
/case10 status
```

## Структура репозитория

```
├── tools/
│   ├── case10_pipeline.py    # Оркестратор pipeline
│   ├── org_validator.py      # Валидация оргструктуры
│   ├── jira_bridge.py        # Jira + Confluence API
│   └── notifier.py           # Уведомления (TG/MM/Email)
├── config/
│   ├── config.yaml           # Основная конфигурация
│   ├── org_structure.yaml    # Оргструктура (шаблон)
│   └── .env.example          # Переменные окружения
├── tests/
│   └── test_pipeline.py      # Тесты с mock-данными
├── SKILL.md                  # Описание навыка Hermes
├── install.sh                # Установщик
├── Makefile                  # Цели сборки/тестов
└── README.md                 # Этот файл
```

## Бюджет LLM

| Статья | Расчёт | Стоимость |
|--------|--------|-----------|
| VPS | 4 vCPU, 4 GB, 20 GB SSD | 1 500–2 500 ₽/мес |
| OpenRouter Gemini 3 Flash | 50 встреч × ~$0.20 | ~800 ₽/мес |
| OpenRouter Nemotron (free) | Бесплатный | 0 ₽/мес |
| Итого | Gemini Flash | ~2 500–3 500 ₽/мес |
| Итого | Nemotron free | ~1 500–2 700 ₽/мес |

© 2026 — Hermes Agent × GenII

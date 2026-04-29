# Case 10 — Формирование задач из неструктурированных данных

**CPU-first pipeline.** Никаких LLM для основной работы. STT через faster-whisper, NER через natasha, парсинг — regex.

## Pipeline

```
Любой источник (текст / аудио / видео)
  → STT (faster-whisper, CPU int8) ← если аудио/видео
  → natasha NER (имена, даты)
  → regex-паттерны (5 типов конструкций)
  → валидация по оргструктуре (граф, BFS)
  → Jira задачи / Confluence протокол
  → уведомления Telegram / Mattermost / Email
  → LLM fallback (опционально, если правила ничего не нашли)
```

## Быстрый старт

```bash
git clone git@github.com:NikolayGusev-astra/case10.git
cd case10
bash install.sh

# Текстовый файл
python -m tools.pipeline --input sample.txt

# Аудио/видео (требуется faster-whisper)
python -m tools.pipeline --video meeting.mp4
python -m tools.pipeline --audio call.wav --json

# С валидацией по оргструктуре
python -m tools.pipeline --input sample.txt --org config/org_structure.yaml
```

## Структура

```
tools/
├── pipeline.py         # Оркестратор
├── stt.py              # faster-whisper STT (CPU)
├── ner_parser.py       # natasha NER + regex (5 паттернов)
├── org_validator.py    # Валидация по оргструктуре
├── jira_bridge.py      # Jira + Confluence API
├── notifier.py         # Telegram / Mattermost / Email
└── llm_fallback.py     # OpenRouter (опционально)
```

## Поддерживаемые паттерны поручений

| Паттерн | Пример |
|---------|--------|
| Императив | `Сергей, подготовь отчёт до пятницы` |
| Потребность | `Владимир, нужен доступ к серверу` |
| Стрелка | `Иванов -> Петров: провести аудит` |
| Тире | `Иванову — сделать отчёт до 15.05` |
| Дательный | `Поручить Кузнецову — обновить доки` |
| Стенограмма | `— Дим, подготовь тексты до четверга` |

## Требования к VPS

| Компонент | Минимум | Рекомендуется |
|-----------|---------|---------------|
| CPU | 2 vCPU | 4 vCPU |
| RAM | 2 GB | 4 GB |
| Диск | 10 GB | 20 GB SSD |
| Модели | faster-whisper tiny + natasha | ~600 MB |

© 2026 — Hermes Assistant

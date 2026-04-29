"""
ner_parser.py — Извлечение поручений из текста с помощью natasha + regex.

Без LLM. Без API. Только CPU.

Pipeline:
  1. natasha NER — находит имена, даты, организации
  2. regex-паттерны — извлекают конструкции поручений
  3. Обогащение — привязка имён из NER к конструкциям

Поддерживаемые паттерны (из кейса):
  - "[Имя], сделай/подготовь/напиши Х до [даты]"  — императив
  - "[Имя], нужно Х"                                 — потребность
  - "[Автор] -> [Исполнитель]: [задача]"              — стрелка
  - "[Имя] — [задача] до [даты]"                     — тире
  - "[Имя]у/е — сделать Х"                           — дательный падеж
  - "[Имя] делаем/сделаем Х"                         — инклюзивный
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Assignment:
    """Raw assignment extracted from text."""
    author: str = ""
    assignee: str = ""
    summary: str = ""
    description: str = ""
    deadline: Optional[str] = None
    priority: str = "medium"
    source: str = "text"
    raw_text: str = ""

    def to_dict(self) -> dict:
        return {
            "author": self.author,
            "assignee": self.assignee,
            "summary": self.summary,
            "description": self.description,
            "deadline": self.deadline,
            "priority": self.priority,
            "source": self.source,
        }


# ---------------------------------------------------------------------------
# natasha wrapper
# ---------------------------------------------------------------------------

_NATASHA_LOADED = False
_SENT = None
_EMB = None
_NAMER = None
_DATEPARSER = None


def _load_natasha():
    """Lazy-load natasha models (downloaded on first use, ~200MB)."""
    global _NATASHA_LOADED, _SENT, _EMB, _NAMER, _DATEPARSER
    if _NATASHA_LOADED:
        return True
    try:
        from natasha import (
            Doc, Segmenter, NewsEmbedding, NewsMorphTagger,
            NewsSyntaxParser, NewsNERTagger, NewsDateParser,
        )
        _EMB = NewsEmbedding()
        _SENT = Segmenter()
        morph = NewsMorphTagger(_EMB)
        syn = NewsSyntaxParser(_EMB)
        _NAMER = NewsNERTagger(_EMB)
        _DATEPARSER = NewsDateParser()
        _NATASHA_LOADED = True
        logger.info("natasha models loaded")
        return True
    except ImportError:
        logger.warning("natasha not installed. Run: pip install natasha")
        return False
    except Exception as exc:
        logger.warning("natasha load failed: %s", exc)
        return False


def extract_entities(text: str) -> dict:
    """Extract named entities and dates from Russian text using natasha.

    Returns:
        {
            "persons": [{"normal": "Иван Иванов", "span": (0, 11), "raw": "Иванов"}],
            "dates": [{"normal": "2026-05-01", "span": (...), "raw": "до пятницы"}],
        }
    """
    if not _load_natasha():
        return {"persons": [], "dates": []}

    from natasha import Doc

    doc = Doc(text)
    doc.segment(_SENT)
    doc.tag_ner(_NAMER)

    persons = []
    dates = []

    for span in doc.spans:
        if span.type == "PER":
            persons.append({
                "normal": span.normal,
                "span": (span.start, span.stop),
                "raw": text[span.start:span.stop],
            })
        elif span.type == "LOC":
            pass  # игнорируем локации

    # Date extraction via DateParser
    try:
        parsed = _DATEPARSER(text)
        if hasattr(parsed, 'as_json'):
            for entry in parsed.as_json:
                if entry.get('type') == 'DATE':
                    dates.append({
                        "normal": entry.get('value', {}).get('year', ''),
                        "span": (0, 0),
                        "raw": entry.get('text', ''),
                    })
    except Exception:
        pass

    # Fallback regex for dates if natasha fails
    if not dates:
        dates = _extract_dates_regex(text)

    return {"persons": persons, "dates": dates}


def _extract_dates_regex(text: str) -> list:
    """Fallback regex date extraction."""
    found = []
    patterns = [
        (r'до\s+(\d{1,2})[.\s](\d{1,2})(?:[.\s](\d{2,4}))?', 'date'),
        (r'(\d{1,2})[.](\d{1,2})[.](\d{2,4})', 'date'),
        (r'до\s+(понедельник[а]?|вторник[а]?|сред[ы]?|четверг[а]?|пятниц[ы]?|суббот[ы]?|воскресень[я]?)', 'weekday'),
    ]
    for pat, kind in patterns:
        for match in re.finditer(pat, text, re.IGNORECASE):
            found.append({
                "normal": match.group(0),
                "span": (match.start(), match.end()),
                "raw": match.group(0),
            })
    return found


# ---------------------------------------------------------------------------
# Regex patterns for assignment extraction
# ---------------------------------------------------------------------------

# Pattern 1: "[Имя], сделай / подготовь / напиши / исправь / ..."
_RE_IMPERATIVE = re.compile(
    r'(?:^|[.?!;\n]\s*[—\-–]?\s*(?:И да|да|кстати|в общем)?[,]?\s*)'  # dialog start
    r'(?P<assignee>[А-ЯЁ][а-яё]+)'                                   # имя
    r'[,]\s*'
    r'(?P<verb>сдела[ййт]|подготовь?|напиши?|исправь?|'
    r'обнови?|проверь?|закрой?|отправь?|собери?|'
    r'проведи?|настрой?|почини?|доделай?|доделать|сделать|подготовить|написать|'
    r'исправить|обновить|проверить|закрыть|отправить|собрать|провести|настроить|починить)'
    r'(?P<task>.*?)(?:[.]|$|до\s)',
    re.IGNORECASE,
)

# Pattern 2: "[Имя], нужно / необходимо / требуется Х"
_RE_NEED = re.compile(
    r'(?:^|[.?!;]\s*[—\-–]?\s*)'
    r'(?P<assignee>[А-ЯЁ][а-яё]+)'
    r'[,]\s*'
    r'(?P<need>нужно|нужен|нужна|необходимо|требуется|надо)'
    r'(?P<task>.*?)(?:[.]|$)',
    re.IGNORECASE,
)

# Pattern 3: "[Автор] -> [Исполнитель]: [задача]"
_RE_ARROW = re.compile(
    r'(?P<author>[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)\s*'
    r'[-—>]{2,3}\s*'
    r'(?P<assignee>[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)\s*:\s*'
    r'(?P<task>.+)',
    re.IGNORECASE,
)

# Pattern 4: "[Имя] — [задача]"
_RE_DASH = re.compile(
    r'(?:^|[.?!;]\s*)'
    r'(?P<assignee>[А-ЯЁ][а-яё]+[а-я]?)\s*'  # может быть в любом падеже
    r'[—\-]\s*'
    r'(?P<task>[А-ЯЁа-яе\s]+?)(?:[.]|$)',
)

# Pattern 5: "Поручить [Имя]у — [задача]" (дательный падеж)
_RE_DATIVE = re.compile(
    r'(?:поруч(?:ить|ение|ается?)\s+)?'
    r'(?P<assignee>[А-ЯЁ][а-яё]+[уею])\s*'
    r'[—\-–]\s*'
    r'(?P<task>.*?)(?:[.]|$)',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

def extract_assignments(text: str) -> List[Assignment]:
    """Extract all assignments from text using rules + natasha.

    Returns list of Assignment dataclass instances.
    """
    assignments: list[Assignment] = []
    seen: Set[str] = set()  # dedup by raw_text

    entities = extract_entities(text)
    person_names = {p["raw"] for p in entities["persons"]}
    person_normals = {p["normal"] for p in entities["persons"]}

    # --- Pattern 1: Imperative ---
    for match in _RE_IMPERATIVE.finditer(text):
        assignee = match.group("assignee")
        verb = match.group("verb")
        task = match.group("task").strip().strip(",").strip()

        # Validate assignee is a known person (if NER available)
        if person_names and assignee not in person_names and assignee not in person_normals:
            continue

        summary = f"{verb} {task}" if task else verb
        dedup_key = f"imp:{assignee}:{summary}"
        if dedup_key not in seen:
            seen.add(dedup_key)
            a = Assignment(
                assignee=assignee,
                summary=summary[:200],
                description=f"{verb} {task}",
                deadline=_find_deadline(match.group(0)),
                raw_text=match.group(0),
            )
            assignments.append(a)

    # --- Pattern 2: Need ---
    for match in _RE_NEED.finditer(text):
        assignee = match.group("assignee")
        task = match.group("task").strip().strip(",").strip()
        if person_names and assignee not in person_names and assignee not in person_normals:
            continue
        dedup_key = f"need:{assignee}:{task}"
        if dedup_key not in seen:
            seen.add(dedup_key)
            a = Assignment(
                assignee=assignee,
                summary=task[:200],
                description=f"Нужно: {task}",
                deadline=_find_deadline(match.group(0)),
                raw_text=match.group(0),
            )
            assignments.append(a)

    # --- Pattern 3: Arrow ---
    for match in _RE_ARROW.finditer(text):
        author = match.group("author").strip()
        assignee = match.group("assignee").strip()
        task = match.group("task").strip()
        dedup_key = f"arrow:{author}:{assignee}:{task}"
        if dedup_key not in seen:
            seen.add(dedup_key)
            a = Assignment(
                author=author,
                assignee=assignee,
                summary=task[:200],
                description=task,
                deadline=_find_deadline(match.group(0)),
                raw_text=match.group(0),
            )
            assignments.append(a)

    # --- Pattern 4: Dash ---
    for match in _RE_DASH.finditer(text):
        raw_assignee = match.group("assignee").strip()
        task = match.group("task").strip()
        # Try to normalize name via natasha
        normalized = _normalize_name(raw_assignee, entities)
        dedup_key = f"dash:{normalized}:{task}"
        if dedup_key not in seen:
            seen.add(dedup_key)
            a = Assignment(
                assignee=normalized or raw_assignee,
                summary=task[:200],
                description=task,
                deadline=_find_deadline(match.group(0)),
                raw_text=match.group(0),
            )
            assignments.append(a)

    # --- Pattern 5: Dative ---
    for match in _RE_DATIVE.finditer(text):
        raw_assignee = match.group("assignee").strip()
        task = match.group("task").strip()
        normalized = _normalize_name(raw_assignee, entities)
        dedup_key = f"dat:{normalized}:{task}"
        if dedup_key not in seen:
            seen.add(dedup_key)
            a = Assignment(
                assignee=normalized or raw_assignee,
                summary=task[:200],
                description=task,
                deadline=_find_deadline(match.group(0)),
                raw_text=match.group(0),
            )
            assignments.append(a)

    # --- Fallback: if nothing found, try LLM ---
    if not assignments:
        logger.info("No rules matched, trying LLM fallback...")
        try:
            from tools.llm_fallback import llm_extract
            llm_result = llm_extract(text)
            if llm_result:
                assignments.extend(llm_result)
        except Exception as exc:
            logger.warning("LLM fallback failed: %s", exc)

    return assignments


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEADLINE_PATTERNS = [
    (r'до\s+(\d{1,2})[.\s](\d{1,2})(?:[.\s](\d{2,4}))?', lambda m: f"до {m.group(1)}.{m.group(2)}"),
    (r'до\s+(понедельник[а]?|вторник[а]?|сред[ы]?|четверг[а]?|пятниц[ы]?|суббот[ы]?|воскресень[я]?)', lambda m: m.group(1)),
    (r'(\d{1,2})[.](\d{1,2})[.](\d{2,4})', lambda m: f"{m.group(1)}.{m.group(2)}.{m.group(3)}"),
    (r'сегодня|завтра|послезавтра', lambda m: m.group(0)),
    (r'срочно', lambda m: m.group(0)),
]


def _find_deadline(text: str) -> Optional[str]:
    """Extract deadline string from text using regex."""
    for pat, formatter in _DEADLINE_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return formatter(m)
    return None


def _normalize_name(raw: str, entities: dict) -> Optional[str]:
    """Try to normalize a name (possibly inflected) via NER."""
    for p in entities.get("persons", []):
        if p["raw"].lower() == raw.lower():
            return p["normal"]
        # Check if raw is a case form
        if raw.lower().rstrip("уеюая") == p["raw"].lower().rstrip("уеюая"):
            return p["normal"]
    return None

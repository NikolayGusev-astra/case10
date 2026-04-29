"""
llm_fallback.py — Optional LLM-based assignment extractor.

Used only when regex rules fail to find any assignments.
Requires OPENROUTER_API_KEY in environment.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from tools.ner_parser import Assignment

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "google/gemini-2.0-flash-001"
LLM_PROMPT = """Ты — система извлечения поручений из текста.

Прочитай текст и найди ВСЕ поручения, задачи и договорённости.
Для каждого поручения верни JSON:
  "author": "кто дал поручение (или пустая строка)",
  "assignee": "кому поручено",
  "summary": "короткое описание задачи",
  "description": "полное описание",
  "deadline": "срок (или null)",
  "priority": "high/medium/low"

Ответь ТОЛЬКО JSON-массивом, без лишнего текста.
Если поручений нет — верни [].
"""


def llm_extract(text: str, model: str = DEFAULT_MODEL) -> Optional[list]:
    """Extract assignments via OpenRouter LLM.

    Returns list of Assignment objects, or None on failure.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        logger.warning("OPENROUTER_API_KEY not set, skipping LLM fallback")
        return None

    try:
        import requests
    except ImportError:
        logger.warning("requests not installed")
        return None

    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": LLM_PROMPT},
                {"role": "user", "content": text[:8000]},
            ],
            "temperature": 0.1,
        },
        timeout=30,
    )

    if not resp.ok:
        logger.error("LLM call failed: %s %s", resp.status_code, resp.text[:200])
        return None

    try:
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        # Strip markdown fences if present
        content = content.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(content)
    except (KeyError, json.JSONDecodeError, IndexError) as exc:
        logger.error("LLM response parse failed: %s", exc)
        return None

    if not isinstance(data, list):
        return None

    assignments = []
    for item in data:
        a = Assignment(
            author=str(item.get("author", "")),
            assignee=str(item.get("assignee", "")),
            summary=str(item.get("summary", "")),
            description=str(item.get("description", "")),
            deadline=str(item.get("deadline")) if item.get("deadline") else None,
            priority=str(item.get("priority", "medium")),
            source="llm_fallback",
            raw_text=text[:100],
        )
        assignments.append(a)

    return assignments if assignments else None

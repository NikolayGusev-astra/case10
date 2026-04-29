"""
pipeline.py — Case 10 pipeline orchestrator.

CPU-first pipeline:
  1. Загрузка текста (или STT из аудио/видео)
  2. Извлечение поручений (natasha NER + regex, LLM fallback)
  3. Валидация по оргструктуре
  4. Создание задач в Jira / Confluence
  5. Уведомления

Usage:
  python -m tools.pipeline --input стенограмма.txt [--org org.yaml] [--jira]
  python -m tools.pipeline --video meeting.mp4
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("pipeline")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ValidatedAssignment:
    assignment: dict
    status: str
    validation_message: str = ""


@dataclass
class Ticket:
    key: str
    url: str
    assignment: dict


@dataclass
class PipelineResult:
    assignments: list = field(default_factory=list)
    validated: list = field(default_factory=list)
    tickets: list = field(default_factory=list)
    protocol_url: Optional[str] = None
    notifications: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def load_text(input_path: str) -> str:
    """Load text from file."""
    with open(input_path, encoding="utf-8") as f:
        return f.read()


def extract_assignments(text: str) -> list:
    """Extract assignments using rules + fallback."""
    from tools.ner_parser import extract_assignments
    return [a.to_dict() for a in extract_assignments(text)]


def validate_assignments(
    assignments: list,
    org_graph: Optional[dict] = None,
) -> list:
    """Validate each assignment against org structure."""
    if not org_graph:
        return [
            ValidatedAssignment(a, "unknown", "Нет оргструктуры для проверки")
            for a in assignments
        ]

    from tools.org_validator import check_authority

    results = []
    for a in assignments:
        status = "unknown"
        msg = ""

        if a.get("author") and a.get("assignee"):
            author = a["author"]
            assignee = a["assignee"]
            # Try to match names to logins in org graph
            author_login = _resolve_login(author, org_graph)
            assignee_login = _resolve_login(assignee, org_graph)

            if author_login and assignee_login:
                status = check_authority(author_login, assignee_login, org_graph)
                msg = _validation_message(status, a)
            else:
                status = "unknown_employee"
                msg = f"Сотрудник не найден в оргструктуре"
        else:
            status = "no_author"
            msg = "Автор или исполнитель не указаны"

        results.append(ValidatedAssignment(a, status, msg))

    return results


def _resolve_login(name: str, org_graph: dict) -> Optional[str]:
    """Try to match a person name to a login in org graph."""
    name_lower = name.lower().strip()
    for login, emp in org_graph.items():
        if name_lower == emp.get("name", "").lower():
            return login
        # Partial match
        emp_parts = emp.get("name", "").lower().split()
        for part in emp_parts:
            if name_lower == part:
                return login
    return None


def _validation_message(status: str, assignment: dict) -> str:
    messages = {
        "valid": "✅ Поручение одобрено: руководитель → подчинённый",
        "cross_functional": "⚠️ Кросс-функциональное: требуется подтверждение",
        "invalid_subordinate_to_manager": "❌ Подчинённый не может поручать руководителю",
        "invalid_authority": "❌ Нет полномочий для поручения",
    }
    return messages.get(status, f"Статус: {status}")


def create_jira_tickets(assignments: list, config: Optional[dict] = None) -> list:
    """Create tickets in Jira for validated assignments."""
    try:
        from tools.jira_bridge import create_jira_task
    except ImportError:
        logger.warning("jira_bridge not available")
        return []

    tickets = []
    for va in assignments:
        if va.status not in ("valid", "cross_functional"):
            continue
        try:
            ticket = create_jira_task(va.assignment)
            if ticket:
                tickets.append(Ticket(ticket["key"], ticket["url"], va.assignment))
        except Exception as exc:
            logger.error("Jira ticket creation failed: %s", exc)
    return tickets


def notify(assignments: list, channels: Optional[list] = None) -> dict:
    """Send notifications about assignments."""
    try:
        from tools.notifier import notify_all
    except ImportError:
        return {}

    if not assignments:
        return {}

    message_parts = ["📋 Извлечённые поручения:\n"]
    for va in assignments:
        a = va.assignment
        message_parts.append(
            f"• {a.get('assignee', '?')}: {a.get('summary', '')[:100]}"
            f" [{va.status}]"
        )

    message = "\n".join(message_parts)
    return notify_all(message, channels=channels or ["telegram"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Case 10 pipeline")
    parser.add_argument("--input", help="Path to text file with meeting transcript")
    parser.add_argument("--video", help="Path to video file (will transcribe via STT)")
    parser.add_argument("--audio", help="Path to audio file (will transcribe via STT)")
    parser.add_argument("--org", default="config/org_structure.yaml", help="Org structure YAML")
    parser.add_argument("--jira", action="store_true", help="Create Jira tickets")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args(argv)

    # Load text
    text = None
    if args.input:
        text = load_text(args.input)
    elif args.video:
        logger.info("Transcribing video...")
        from tools.stt import transcribe_video
        text = transcribe_video(args.video)
    elif args.audio:
        logger.info("Transcribing audio...")
        from tools.stt import transcribe
        text = transcribe(args.audio)
    else:
        # Read from stdin
        text = sys.stdin.read()

    if not text:
        logger.error("No input text")
        return 1

    logger.info("Text length: %d chars", len(text))

    # Step 1: Extract assignments
    logger.info("Extracting assignments...")
    raw = extract_assignments(text)
    logger.info("Found %d raw assignments", len(raw))

    # Step 2: Validate
    org_graph = None
    if os.path.exists(args.org):
        try:
            from tools.org_validator import load_org_graph
            org_graph = load_org_graph(args.org)
            logger.info("Org structure loaded: %d employees", len(org_graph))
        except Exception as exc:
            logger.warning("Failed to load org structure: %s", exc)

    validated = validate_assignments(raw, org_graph)

    # Step 3: Jira
    tickets = []
    if args.jira:
        tickets = create_jira_tickets(validated)

    # Step 4: Notify
    notification_results = notify(validated)

    # Build result
    result = PipelineResult(
        assignments=raw,
        validated=[{"assignment": va.assignment, "status": va.status, "message": va.validation_message} for va in validated],
        tickets=[{"key": t.key, "url": t.url} for t in tickets],
        notifications=notification_results,
    )

    if args.json:
        print(json.dumps(
            {"assignments": raw, "validated": result.validated, "tickets": result.tickets},
            ensure_ascii=False, indent=2, default=str,
        ))
    else:
        print(f"\n{'='*60}")
        print(f"Найдено поручений: {len(raw)}")
        print(f"{'='*60}")
        for va in validated:
            a = va.assignment
            print(f"\n  {va.validation_message}")
            print(f"  Кому: {a.get('assignee', '?')}")
            print(f"  Что:  {a.get('summary', '')[:100]}")
            if a.get("deadline"):
                print(f"  Срок: {a['deadline']}")
            if a.get("author"):
                print(f"  От:   {a['author']}")

        if tickets:
            print(f"\n  Создано задач в Jira: {len(tickets)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

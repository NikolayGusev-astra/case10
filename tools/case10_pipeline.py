"""
case10_pipeline.py — Core pipeline orchestrator for Case 10.

Extracts structured tasks/assignments from unstructured text sources
(email, meeting transcripts, notes, protocols) using an LLM (via
OpenRouter), validates assignments against the organisational structure,
creates Jira tickets, publishes a Confluence protocol page, and sends
notifications.

Pipeline flow:
  1. parse_unstructured_text(text) -> list[Assignment]
  2. validate_assignments(assignments, org_graph) -> list[ValidatedAssignment]
  3. create_tickets(assignments, jira_config) -> list[Ticket]
  4. publish_protocol(assignments, confluence_config) -> Page
  5. notify(assignments, channels) -> dict[str, bool]

CLI usage:
  python -m tools.case10_pipeline \\
      --input text.txt \\
      --org config/org_structure.yaml \\
      --config config/config.yaml

Hermes skill integration:
  Register as a tool with @registry.register(...) so that the pipeline
  is callable from within a Hermes Agent session.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

import yaml

from tools.org_validator import load_org_graph, check_authority
from tools.notifier import notify_all

logger = logging.getLogger("case10_pipeline")

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Assignment:
    """Raw assignment extracted from unstructured text."""
    author: str          # Who gave the task (login or full name)
    assignee: str        # Who is responsible
    summary: str         # Short title
    description: str     # Full description
    deadline: str | None = None   # ISO date or free-text
    priority: str = "Medium"      # High / Medium / Low
    source: str = "manual"        # email | transcript | protocol | note

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidatedAssignment:
    """Assignment enriched with organisational validation result."""
    assignment: Assignment
    status: str                       # valid | cross_functional | invalid_*
    validation_message: str = ""


@dataclass
class Ticket:
    """Result of creating a Jira ticket."""
    key: str
    url: str
    assignment: Assignment


@dataclass
class PipelineResult:
    """Full result of a pipeline run."""
    assignments: list[Assignment] = field(default_factory=list)
    validated: list[ValidatedAssignment] = field(default_factory=list)
    tickets: list[Ticket] = field(default_factory=list)
    protocol_url: str | None = None
    notifications: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# LLM parsing (OpenRouter)
# ---------------------------------------------------------------------------

def _openrouter_parse(text: str, model: str = "google/gemini-2.0-flash-001") -> list[Assignment]:
    """Use OpenRouter-compatible LLM to extract assignments from *text*.

    Falls back to a simple regex heuristic if the API call fails.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        logger.warning("OPENROUTER_API_KEY not set — using fallback parser")
        return _fallback_parse(text)

    prompt = (
        "Ты — ассистент, извлекающий поручения из неструктурированного текста. "
        "Ответь строго в формате JSON-массива объектов с полями:\n"
        "  author (кто дал поручение),\n"
        "  assignee (кому дано),\n"
        "  summary (краткое название задачи),\n"
        "  description (полное описание),\n"
        "  deadline (срок, если указан, иначе null),\n"
        "  priority (High/Medium/Low, по умолчанию Medium).\n\n"
        f"Текст:\n{text}\n\nJSON:"
    )

    try:
        import requests
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 4096,
            },
            timeout=60,
        )
        resp.raise_for_status()
        raw = resp.json()
        content = raw["choices"][0]["message"]["content"]
        # Strip markdown fences if present
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        data = json.loads(content)
        if isinstance(data, dict):
            data = data.get("assignments", data.get("tasks", [data]))
        return [Assignment(**item) for item in data]
    except Exception as exc:
        logger.warning("OpenRouter parse failed (%s), using fallback", exc)
        return _fallback_parse(text)


def _fallback_parse(text: str) -> list[Assignment]:
    """Simple regex-based fallback parser.

    Looks for patterns like:
      - "Иванов -> Петров: сделать отчёт до 15.05"
      - "Поручение: Иванов поручает Петрову ..."
    """
    import re
    assignments: list[Assignment] = []

    # Pattern: Author -> Assignee: summary [до deadline]
    pattern = re.compile(
        r"(?P<author>[А-Яа-яA-Za-z]+)\s*[-–—>]+\s*"
        r"(?P<assignee>[А-Яа-яA-Za-z]+)\s*:\s*"
        r"(?P<summary>.+?)(?:\s+до\s+(?P<deadline>\S+))?(?:\n|$)",
        re.MULTILINE,
    )

    for match in pattern.finditer(text):
        assignments.append(
            Assignment(
                author=match.group("author"),
                assignee=match.group("assignee"),
                summary=match.group("summary").strip(),
                description=match.group(0).strip(),
                deadline=match.group("deadline"),
                source="text",
            )
        )

    return assignments


# ===================================================================
# Pipeline stages
# ===================================================================

def parse_unstructured_text(text: str, model: str | None = None) -> list[Assignment]:
    """Stage 1: Parse unstructured text into structured assignments."""
    logger.info("Parsing %d characters of text…", len(text))
    if model:
        return _openrouter_parse(text, model=model)
    return _openrouter_parse(text)


def validate_assignments(
    assignments: list[Assignment],
    org_graph: dict[str, Any],
) -> list[ValidatedAssignment]:
    """Stage 2: Validate each assignment against the org structure."""
    validated: list[ValidatedAssignment] = []
    for a in assignments:
        status = check_authority(a.author, a.assignee, org_graph)
        msg = _validation_message(status, a)
        validated.append(ValidatedAssignment(assignment=a, status=status, validation_message=msg))
    return validated


def _validation_message(status: str, a: Assignment) -> str:
    messages = {
        "valid": (
            f"[OK] {a.author} -> {a.assignee}: поручение одобрено "
            f"(руководитель поручает подчинённому)"
        ),
        "cross_functional": (
            f"[WARN] {a.author} -> {a.assignee}: межфункциональное поручение — "
            f"требуется подтверждение вышестоящего руководителя"
        ),
        "invalid_authority": (
            f"[BLOCK] {a.author} -> {a.assignee}: недостаточно полномочий — "
            f"поручение не может быть создано"
        ),
        "invalid_subordinate_to_manager": (
            f"[BLOCK] {a.author} -> {a.assignee}: подчинённый не может "
            f"назначать задачи руководителю"
        ),
    }
    return messages.get(status, f"[UNKNOWN] Статус: {status}")


def create_tickets(
    assignments: list[ValidatedAssignment],
    jira_project: str = "TASKS",
    jira_config: dict[str, Any] | None = None,
) -> list[Ticket]:
    """Stage 3: Create Jira tickets for valid assignments.

    Skips invalid assignments (returns placeholder with error info).
    """
    from tools.jira_bridge import create_jira_task

    tickets: list[Ticket] = []
    for va in assignments:
        if va.status not in ("valid", "cross_functional"):
            logger.info("Skipping ticket creation for %s (status=%s)", va.assignment.summary, va.status)
            continue

        try:
            issue = create_jira_task(
                project=jira_project,
                summary=va.assignment.summary,
                description=va.assignment.description,
                assignee=va.assignment.assignee,
                priority=va.assignment.priority,
                deadline=va.assignment.deadline,
            )
            tickets.append(
                Ticket(
                    key=issue.get("key", "???"),
                    url=issue.get("self", ""),
                    assignment=va.assignment,
                )
            )
        except Exception as exc:
            logger.error("Failed to create ticket: %s", exc)
            tickets.append(
                Ticket(key="ERROR", url="", assignment=va.assignment)
            )

    return tickets


def publish_protocol(
    assignments: list[ValidatedAssignment],
    space: str = "TASKS",
    title: str | None = None,
) -> str | None:
    """Stage 4: Publish a protocol page in Confluence with all parsed tasks."""
    from tools.jira_bridge import create_confluence_page

    if title is None:
        title = f"Протокол разбора поручений от {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    lines = [
        "<h1>Протокол разбора неструктурированных данных</h1>",
        f"<p>Сформирован: {datetime.now().isoformat()}</p>",
        "<hr/>",
        "<h2>Поручения</h2>",
        "<table><tr><th>#</th><th>Автор</th><th>Исполнитель</th><th>Задача</th>"
        "<th>Срок</th><th>Приоритет</th><th>Статус</th></tr>",
    ]
    for idx, va in enumerate(assignments, 1):
        icon = {"valid": "✅", "cross_functional": "⚠️", "invalid_authority": "❌",
                "invalid_subordinate_to_manager": "🚫"}.get(va.status, "❓")
        lines.append(
            f"<tr><td>{idx}</td><td>{va.assignment.author}</td>"
            f"<td>{va.assignment.assignee}</td><td>{va.assignment.summary}</td>"
            f"<td>{va.assignment.deadline or '-'}</td>"
            f"<td>{va.assignment.priority}</td>"
            f"<td>{icon} {va.status}</td></tr>"
        )
    lines.append("</table><hr/><p><i>Сгенерировано Case 10 Pipeline</i></p>")

    try:
        page = create_confluence_page(space=space, title=title, content="\n".join(lines))
        return f"{os.environ.get('CONFLUENCE_URL', '')}/spaces/{space}/pages/{page.get('id', '')}"
    except Exception as exc:
        logger.error("Failed to publish Confluence page: %s", exc)
        return None


def notify(assignments: list[ValidatedAssignment], channels: list[str] | None = None) -> dict[str, bool]:
    """Stage 5: Send notifications about created assignments."""
    valid_count = sum(1 for va in assignments if va.status == "valid")
    cross_count = sum(1 for va in assignments if va.status == "cross_functional")
    blocked_count = sum(1 for va in assignments if va.status not in ("valid", "cross_functional"))

    message = (
        f"<b>Case 10 Pipeline — отчёт</b>\n"
        f"Всего поручений: {len(assignments)}\n"
        f"✅ Создано: {valid_count}\n"
        f"⚠️ Требуют подтверждения: {cross_count}\n"
        f"❌ Заблокировано: {blocked_count}\n\n"
        f"Детали:\n"
    )
    for va in assignments:
        message += f"  • {va.validation_message}\n"

    return notify_all(message.strip(), channels=channels)


# ===================================================================
# Full pipeline
# ===================================================================

def run_pipeline(
    text: str,
    org_path: str = "config/org_structure.yaml",
    jira_project: str = "TASKS",
    confluence_space: str = "TASKS",
    channels: list[str] | None = None,
    model: str | None = None,
) -> PipelineResult:
    """Execute the full Case 10 pipeline end-to-end.

    Args:
        text: Unstructured input text.
        org_path: Path to the YAML organisational structure file.
        jira_project: Jira project key.
        confluence_space: Confluence space key.
        channels: Notification channels to use.
        model: OpenRouter model name (e.g. "google/gemini-2.0-flash-001").

    Returns:
        PipelineResult with all stages' outputs.
    """
    result = PipelineResult()
    logger.info("=== Case 10 Pipeline start ===")

    # Stage 1 — Parse
    try:
        result.assignments = parse_unstructured_text(text, model=model)
        logger.info("Parsed %d assignments", len(result.assignments))
    except Exception as exc:
        result.errors.append(f"Parse failed: {exc}")
        logger.error("Parse failed: %s", exc)
        return result

    if not result.assignments:
        logger.warning("No assignments found in input text")
        return result

    # Stage 2 — Validate
    try:
        org = load_org_graph(org_path)
        result.validated = validate_assignments(result.assignments, org)
    except Exception as exc:
        result.errors.append(f"Validation failed: {exc}")
        return result

    # Stage 3 — Create tickets
    try:
        result.tickets = create_tickets(result.validated, jira_project=jira_project)
    except Exception as exc:
        result.errors.append(f"Ticket creation failed: {exc}")

    # Stage 4 — Publish protocol
    try:
        result.protocol_url = publish_protocol(result.validated, space=confluence_space)
    except Exception as exc:
        result.errors.append(f"Protocol publish failed: {exc}")

    # Stage 5 — Notify
    try:
        result.notifications = notify(result.validated, channels=channels or ["telegram"])
    except Exception as exc:
        result.errors.append(f"Notification failed: {exc}")

    logger.info("=== Case 10 Pipeline complete ===")
    return result


# ===================================================================
# CLI entry point
# ===================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Case 10 — Pipeline извлечения поручений из неструктурированных данных"
    )
    parser.add_argument("--input", "-i", required=True,
                        help="Path to input text file (or '-' for stdin)")
    parser.add_argument("--org", "-o", default="config/org_structure.yaml",
                        help="Path to org structure YAML")
    parser.add_argument("--config", "-c", default="config/config.yaml",
                        help="Path to configuration YAML")
    parser.add_argument("--jira-project", default="TASKS",
                        help="Jira project key")
    parser.add_argument("--confluence-space", default="TASKS",
                        help="Confluence space key")
    parser.add_argument("--model", default=None,
                        help="OpenRouter model name")
    parser.add_argument("--channels", nargs="*", default=["telegram"],
                        help="Notification channels")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Load config
    if os.path.isfile(args.config):
        with open(args.config, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        args.jira_project = cfg.get("jira", {}).get("project", args.jira_project)
        args.confluence_space = cfg.get("confluence", {}).get("space", args.confluence_space)
        args.channels = cfg.get("notifications", {}).get("channels", args.channels)

    # Read input
    if args.input == "-":
        text = sys.stdin.read()
    else:
        with open(args.input, encoding="utf-8") as fh:
            text = fh.read()

    # Run
    result = run_pipeline(
        text=text,
        org_path=args.org,
        jira_project=args.jira_project,
        confluence_space=args.confluence_space,
        channels=args.channels,
        model=args.model,
    )

    # Report
    print("\n=== Pipeline Results ===")
    print(f"Assignments parsed:  {len(result.assignments)}")
    print(f"Validated:           {len(result.validated)}")
    print(f"Tickets created:     {len([t for t in result.tickets if t.key != 'ERROR'])}")
    print(f"Protocol URL:        {result.protocol_url or '(not published)'}")
    print(f"Notifications:       {result.notifications}")
    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for e in result.errors:
            print(f"  - {e}")

    sys.exit(1 if result.errors else 0)


if __name__ == "__main__":
    main()

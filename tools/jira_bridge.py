"""
jira_bridge.py — Jira task creation and Confluence page publishing.

Thin wrappers around the Atlassian Python SDK (atlassian-python-api).
All credentials are loaded from environment variables or the central config.

Usage:
  from tools.jira_bridge import create_jira_task, create_confluence_page
  issue = create_jira_task("PROJ", "Fix login bug", "Details...", "jdoe", "High", "2026-05-15")
  page = create_confluence_page("DEV", "Protocol 2026-04-29", "# Meeting notes...")
"""

from __future__ import annotations

import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency — atlassian-python-api
# ---------------------------------------------------------------------------

try:
    from atlassian import Confluence, Jira
except ImportError:
    Confluence = None  # type: ignore[assignment]
    Jira = None  # type: ignore[assignment]


def _jira_client() -> Any:
    """Return an authenticated Jira client or raise."""
    if Jira is None:
        raise ImportError(
            "Missing atlassian-python-api. Install: pip install atlassian-python-api"
        )
    return Jira(
        url=os.environ.get("JIRA_URL", ""),
        username=os.environ.get("JIRA_USERNAME"),
        password=os.environ.get("JIRA_API_TOKEN"),
        cloud=os.environ.get("JIRA_CLOUD", "true").lower() == "true",
    )


def _confluence_client() -> Any:
    """Return an authenticated Confluence client or raise."""
    if Confluence is None:
        raise ImportError(
            "Missing atlassian-python-api. Install: pip install atlassian-python-api"
        )
    return Confluence(
        url=os.environ.get("CONFLUENCE_URL", ""),
        username=os.environ.get("CONFLUENCE_USERNAME"),
        password=os.environ.get("CONFLUENCE_API_TOKEN"),
        cloud=os.environ.get("CONFLUENCE_CLOUD", "true").lower() == "true",
    )


# ---------------------------------------------------------------------------
# Issue creation
# ---------------------------------------------------------------------------

def create_jira_task(
    project: str,
    summary: str,
    description: str = "",
    assignee: str | None = None,
    priority: str = "Medium",
    deadline: str | None = None,
    issue_type: str = "Task",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Create a Jira issue and return its metadata dict.

    Returns at least ``{"key": ..., "id": ..., "self": ...}``.
    """
    client = _jira_client()

    fields: dict[str, Any] = {
        "project": {"key": project},
        "summary": summary,
        "description": description,
        "issuetype": {"name": issue_type},
        "priority": {"name": priority},
    }

    if assignee:
        # Try to resolve user — the SDK accepts accountId for cloud
        fields["assignee"] = {"id": assignee}

    if labels:
        fields["labels"] = labels

    if deadline:
        # Standard Jira field for due date
        fields["duedate"] = deadline

    issue = client.create_issue(fields=fields)
    logger.info("Created Jira issue %s", issue.get("key", "???"))
    return issue


# ---------------------------------------------------------------------------
# Confluence page creation
# ---------------------------------------------------------------------------

def create_confluence_page(
    space: str,
    title: str,
    content: str,
    parent_id: str | None = None,
) -> dict[str, Any]:
    """Create (or update if exists) a Confluence page.

    *content* can be Markdown or Confluence Storage Format (XHTML).
    Returns the page metadata dict.
    """
    client = _confluence_client()

    # Check if page already exists
    existing = client.get_page_by_title(space=space, title=title)
    if existing:
        logger.info("Page '%s' exists (id=%s), updating…", title, existing["id"])
        client.update_page(
            page_id=existing["id"],
            title=title,
            body=content,
            representation="storage",
            minor_edit=False,
        )
        return existing

    page = client.create_page(
        space=space,
        title=title,
        body=content,
        parent_id=parent_id,
        representation="storage",
    )
    logger.info("Created Confluence page '%s' (id=%s)", title, page.get("id", "???"))
    return page

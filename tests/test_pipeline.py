"""
Tests for Case 10 pipeline components.

Run with:
    cd /tmp/case10 && python -m pytest tests/test_pipeline.py -v

Or:
    make test
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import yaml

# Ensure tools package is importable
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# Sample org structure for tests
# ---------------------------------------------------------------------------

SAMPLE_ORG = {
    "employees": [
        {
            "login": "ceo",
            "name": "Генеральный директор",
            "role": "CEO",
            "team": "Руководство",
            "manager": None,
            "subordinates": ["dev_dir", "prod_dir"],
        },
        {
            "login": "dev_dir",
            "name": "Директор по разработке",
            "role": "Development Director",
            "team": "Разработка",
            "manager": "ceo",
            "subordinates": ["tl_backend", "tl_frontend"],
        },
        {
            "login": "prod_dir",
            "name": "Директор по продукту",
            "role": "Product Director",
            "team": "Продукт",
            "manager": "ceo",
            "subordinates": ["pm"],
        },
        {
            "login": "tl_backend",
            "name": "Team Lead Backend",
            "role": "TL",
            "team": "Разработка",
            "manager": "dev_dir",
            "subordinates": ["dev_backend"],
        },
        {
            "login": "tl_frontend",
            "name": "Team Lead Frontend",
            "role": "TL",
            "team": "Разработка",
            "manager": "dev_dir",
            "subordinates": ["dev_frontend"],
        },
        {
            "login": "dev_backend",
            "name": "Backend Developer",
            "role": "Developer",
            "team": "Разработка",
            "manager": "tl_backend",
            "subordinates": [],
        },
        {
            "login": "dev_frontend",
            "name": "Frontend Developer",
            "role": "Developer",
            "team": "Разработка",
            "manager": "tl_frontend",
            "subordinates": [],
        },
        {
            "login": "pm",
            "name": "Product Manager",
            "role": "PM",
            "team": "Продукт",
            "manager": "prod_dir",
            "subordinates": [],
        },
        {
            "login": "qa_lead",
            "name": "QA Lead",
            "role": "QA Lead",
            "team": "QA",
            "manager": None,
            "subordinates": ["qa_eng"],
        },
        {
            "login": "qa_eng",
            "name": "QA Engineer",
            "role": "QA",
            "team": "QA",
            "manager": "qa_lead",
            "subordinates": [],
        },
    ]
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_org_yaml(path: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        yaml.dump(SAMPLE_ORG, fh, allow_unicode=True)
    return path


# ===================================================================
# Tests: org_validator
# ===================================================================

class TestOrgValidator:

    def setup_method(self) -> None:
        from tools.org_validator import load_org_graph
        self.tmp = tempfile.mktemp(suffix=".yaml")
        _write_org_yaml(self.tmp)
        self.org = load_org_graph(self.tmp)

    def teardown_method(self) -> None:
        if os.path.isfile(self.tmp):
            os.remove(self.tmp)

    def test_load_org_graph(self) -> None:
        assert "dev_dir" in self.org
        assert self.org["dev_dir"]["manager"] == "ceo"
        assert self.org["dev_dir"]["team"] == "Разработка"

    def test_manager_to_subordinate_valid(self) -> None:
        from tools.org_validator import check_authority
        status = check_authority("dev_dir", "tl_backend", self.org)
        assert status == "valid", f"Expected valid, got {status}"

    def test_subordinate_to_manager_invalid(self) -> None:
        from tools.org_validator import check_authority
        status = check_authority("dev_backend", "tl_backend", self.org)
        assert status == "invalid_subordinate_to_manager", f"Expected invalid_subordinate_to_manager, got {status}"

    def test_cross_functional(self) -> None:
        from tools.org_validator import check_authority
        status = check_authority("dev_dir", "pm", self.org)
        assert status == "cross_functional", f"Expected cross_functional, got {status}"

    def test_no_authority(self) -> None:
        from tools.org_validator import check_authority
        status = check_authority("dev_backend", "qa_lead", self.org)
        assert status == "invalid_authority", f"Expected invalid_authority, got {status}"

    def test_find_subordinates(self) -> None:
        from tools.org_validator import find_subordinates
        subs = find_subordinates("dev_dir", self.org)
        assert "tl_backend" in subs
        assert "tl_frontend" in subs
        assert "dev_backend" not in subs  # depth default = 1

    def test_find_subordinates_deep(self) -> None:
        from tools.org_validator import find_subordinates
        subs = find_subordinates("ceo", self.org, depth=-1)
        assert "dev_dir" in subs
        assert "tl_backend" in subs
        assert "dev_backend" in subs

    def test_find_manager_chain(self) -> None:
        from tools.org_validator import find_manager_chain
        chain = find_manager_chain("dev_backend", self.org)
        assert chain == ["tl_backend", "dev_dir", "ceo"]


# ===================================================================
# Tests: case10_pipeline
# ===================================================================

SAMPLE_TEXT = """\
Иванов -> Петров: подготовить отчёт до 15.05.

На совещании директор поручил:
- Кузнецову — обновить документацию до 05.05.
"""


class TestPipeline:

    def setup_method(self) -> None:
        self.tmp_org = tempfile.mktemp(suffix=".yaml")
        _write_org_yaml(self.tmp_org)

    def teardown_method(self) -> None:
        if os.path.isfile(self.tmp_org):
            os.remove(self.tmp_org)

    def test_fallback_parser(self) -> None:
        from tools.case10_pipeline import _fallback_parse
        assignments = _fallback_parse(SAMPLE_TEXT)
        # The fallback parser should find at least the Ivanov -> Petrov pattern
        assert len(assignments) >= 1
        if assignments:
            assert assignments[0].author == "Иванов" or assignments[0].assignee == "Петров"

    def test_validate_assignments(self) -> None:
        from tools.case10_pipeline import parse_unstructured_text, validate_assignments
        from tools.org_validator import load_org_graph

        # Use fallback (no API key)
        os.environ.pop("OPENROUTER_API_KEY", None)
        assignments = parse_unstructured_text(SAMPLE_TEXT)
        org = load_org_graph(self.tmp_org)
        validated = validate_assignments(assignments, org)

        assert isinstance(validated, list)
        for va in validated:
            assert va.status in (
                "valid", "cross_functional", "invalid_authority",
                "invalid_subordinate_to_manager"
            )

    def test_validation_message(self) -> None:
        from tools.case10_pipeline import _validation_message
        from tools.case10_pipeline import Assignment

        a = Assignment(author="dev_dir", assignee="tl_backend", summary="Test", description="")
        msg = _validation_message("valid", a)
        assert "одобрено" in msg

        msg2 = _validation_message("invalid_subordinate_to_manager", a)
        assert "подчинённый не может" in msg2

    def test_pipeline_result_dataclass(self) -> None:
        from tools.case10_pipeline import PipelineResult, Assignment, ValidatedAssignment, Ticket

        result = PipelineResult()
        assert result.assignments == []
        assert result.errors == []

        a = Assignment(author="dev_dir", assignee="dev_backend", summary="Fix bug", description="")
        va = ValidatedAssignment(assignment=a, status="valid")
        t = Ticket(key="TASKS-1", url="http://jira/TASKS-1", assignment=a)

        result.assignments.append(a)
        result.validated.append(va)
        result.tickets.append(t)

        assert len(result.assignments) == 1
        assert result.tickets[0].key == "TASKS-1"


# ===================================================================
# Tests: notifier
# ===================================================================

class TestNotifier:

    def test_notify_all_no_channels(self) -> None:
        """notify_all with empty channels should return empty dict."""
        from tools.notifier import notify_all
        result = notify_all("test", channels=[])
        assert result == {}

    def test_unknown_channel(self) -> None:
        """Unknown channel should return False."""
        from tools.notifier import notify_all
        result = notify_all("test", channels=["nonexistent"])
        assert result == {"nonexistent": False}

    def test_send_email_no_creds(self) -> None:
        """send_email should return False when SMTP not configured."""
        from tools.notifier import send_email
        # Ensure no SMTP env vars are set
        for k in ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"]:
            os.environ.pop(k, None)
        result = send_email("Subject", "Body", "test@example.com")
        assert result is False

    def test_send_telegram_no_creds(self) -> None:
        """send_telegram should return False when token not set."""
        from tools.notifier import send_telegram
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        result = send_telegram("test")
        assert result is False


# ===================================================================
# Tests: jira_bridge
# ===================================================================

class TestJiraBridge:

    def test_import(self) -> None:
        """Ensure imports work (no-op if atlassian SDK missing)."""
        try:
            from tools.jira_bridge import create_jira_task, create_confluence_page
            assert callable(create_jira_task)
        except ImportError:
            pass  # SDK not installed — that's acceptable

"""
Tests for Case 10 CPU-first pipeline components.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# Sample org structure
# ---------------------------------------------------------------------------

SAMPLE_ORG = {
    "employees": [
        {"login": "ceo", "name": "Генеральный директор", "role": "CEO", "team": "Руководство",
         "manager": None, "subordinates": ["dev_dir", "prod_dir"]},
        {"login": "dev_dir", "name": "Директор по разработке", "role": "Development Director",
         "team": "Разработка", "manager": "ceo", "subordinates": ["tl_backend", "tl_frontend"]},
        {"login": "prod_dir", "name": "Директор по продукту", "role": "Product Director",
         "team": "Продукт", "manager": "ceo", "subordinates": ["pm"]},
        {"login": "tl_backend", "name": "Team Lead Backend", "role": "TL",
         "team": "Разработка", "manager": "dev_dir", "subordinates": ["dev_backend"]},
        {"login": "tl_frontend", "name": "Team Lead Frontend", "role": "TL",
         "team": "Разработка", "manager": "dev_dir", "subordinates": ["dev_frontend"]},
        {"login": "dev_backend", "name": "Backend Developer", "role": "Developer",
         "team": "Разработка", "manager": "tl_backend", "subordinates": []},
        {"login": "dev_frontend", "name": "Frontend Developer", "role": "Developer",
         "team": "Разработка", "manager": "tl_frontend", "subordinates": []},
        {"login": "pm", "name": "Product Manager", "role": "PM",
         "team": "Продукт", "manager": "prod_dir", "subordinates": []},
        {"login": "qa_lead", "name": "QA Lead", "role": "QA Lead",
         "team": "QA", "manager": None, "subordinates": ["qa_eng"]},
        {"login": "qa_eng", "name": "QA Engineer", "role": "QA",
         "team": "QA", "manager": "qa_lead", "subordinates": []},
    ]
}


def _write_org_yaml(path: str) -> str:
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(SAMPLE_ORG, f, allow_unicode=True)
    return path


SAMPLE_TEXTS = {
    "imperative": "Сергей, подготовь отчёт по продажам до пятницы.",
    "need": "Владимир, нужен доступ к серверу для тестирования.",
    "arrow": "Иванов -> Петров: провести аудит базы данных до 15.05.",
    "dash": "Иванову — сделать отчёт до 20 мая.",
    "dative": "Поручить Кузнецову — обновить документацию.",
    "full_stenogram": """— Сергей, как там лендинг?
— Готовим, Кабан Кабаныч. Дим, подготовь тексты до четверга.
— Владимир, нужен доступ к серверу для тестирования формы.
— И да, Алексей, собери аналитику по конкурентам за прошлый месяц.""",
}


# ===================================================================
# Tests: NER Parser
# ===================================================================

class TestNERParser:

    def test_imperative(self):
        from tools.ner_parser import extract_assignments
        result = extract_assignments(SAMPLE_TEXTS["imperative"])
        assert len(result) >= 1, "Should find imperative assignment"
        a = result[0]
        assert a.assignee == "Сергей", f"Expected Сергей, got {a.assignee}"
        assert "отчёт" in a.summary.lower(), f"Expected отчёт, got {a.summary}"

    def test_need(self):
        from tools.ner_parser import extract_assignments
        result = extract_assignments(SAMPLE_TEXTS["need"])
        assert len(result) >= 1
        a = result[0]
        assert a.assignee == "Владимир"
        assert "доступ" in a.summary.lower()

    def test_arrow(self):
        from tools.ner_parser import extract_assignments
        result = extract_assignments(SAMPLE_TEXTS["arrow"])
        assert len(result) >= 1
        a = result[0]
        assert a.author == "Иванов"
        assert a.assignee == "Петров"
        assert "аудит" in a.summary.lower()

    def test_dash(self):
        from tools.ner_parser import extract_assignments
        result = extract_assignments(SAMPLE_TEXTS["dash"])
        assert len(result) >= 1
        a = result[0]
        assert "отчёт" in a.summary.lower()

    def test_dative(self):
        from tools.ner_parser import extract_assignments
        result = extract_assignments(SAMPLE_TEXTS["dative"])
        assert len(result) >= 1
        a = result[0]
        assert "документаци" in a.summary.lower()

    def test_full_stenogram(self):
        from tools.ner_parser import extract_assignments
        result = extract_assignments(SAMPLE_TEXTS["full_stenogram"])
        assert len(result) >= 2, f"Expected 2+ assignments, got {len(result)}"
        found = [a.assignee for a in result]
        assert "Сергей" in found or "Дим" in found, f"Expected familiar names, got {found}"

    def test_empty_text(self):
        from tools.ner_parser import extract_assignments
        result = extract_assignments("")
        assert result == []

    def test_no_persons_found(self):
        from tools.ner_parser import extract_assignments
        result = extract_assignments("Погода сегодня хорошая.")
        assert isinstance(result, list)


# ===================================================================
# Tests: Org Validator
# ===================================================================

class TestOrgValidator:

    def setup_method(self):
        from tools.org_validator import load_org_graph
        self.tmp = tempfile.mktemp(suffix=".yaml")
        _write_org_yaml(self.tmp)
        self.org = load_org_graph(self.tmp)

    def teardown_method(self):
        if os.path.isfile(self.tmp):
            os.remove(self.tmp)

    def test_manager_to_subordinate(self):
        from tools.org_validator import check_authority
        assert check_authority("dev_dir", "tl_backend", self.org) == "valid"

    def test_subordinate_to_manager(self):
        from tools.org_validator import check_authority
        assert check_authority("dev_backend", "tl_backend", self.org) == "invalid_subordinate_to_manager"

    def test_cross_functional(self):
        from tools.org_validator import check_authority
        assert check_authority("dev_dir", "pm", self.org) == "cross_functional"

    def test_no_authority(self):
        from tools.org_validator import check_authority
        assert check_authority("dev_backend", "qa_lead", self.org) == "invalid_authority"

    def test_find_subordinates_deep(self):
        from tools.org_validator import find_subordinates
        subs = find_subordinates("ceo", self.org, depth=-1)
        assert "dev_dir" in subs
        assert "dev_backend" in subs

    def test_find_manager_chain(self):
        from tools.org_validator import find_manager_chain
        chain = find_manager_chain("dev_backend", self.org)
        assert chain == ["tl_backend", "dev_dir", "ceo"]


# ===================================================================
# Tests: Pipeline
# ===================================================================

class TestPipeline:

    def test_extract_via_pipeline(self):
        from tools.pipeline import extract_assignments
        result = extract_assignments(SAMPLE_TEXTS["full_stenogram"])
        assert len(result) >= 2

    def test_validate_no_org(self):
        from tools.pipeline import validate_assignments
        assignments = [{"assignee": "Сергей", "summary": "test", "author": ""}]
        validated = validate_assignments(assignments, org_graph=None)
        assert len(validated) == 1
        assert validated[0].status == "unknown"


# ===================================================================
# Tests: Notifier
# ===================================================================

class TestNotifier:

    def test_unknown_channel(self):
        from tools.notifier import notify_all
        assert notify_all("test", channels=["nonexistent"]) == {"nonexistent": False}

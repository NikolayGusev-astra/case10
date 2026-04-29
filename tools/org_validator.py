"""
org_validator.py — Validation of assignments against organisational structure.

Loads an org graph (YAML) and checks authority relationships between
employees to determine whether a task assignment is valid.

Validation statuses:
  - "valid"                          Manager -> subordinate
  - "cross_functional"                Cross-team, needs confirmation
  - "invalid_authority"               No authority relationship
  - "invalid_subordinate_to_manager"  Subordinate -> manager (blocked)

Usage:
  from tools.org_validator import load_org_graph, check_authority
  org = load_org_graph("config/org_structure.yaml")
  status = check_authority("ivan.ivanov", "petr.petrov", org)
"""

from __future__ import annotations

import os
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Data model helpers
# ---------------------------------------------------------------------------

OrgGraph = dict[str, dict[str, Any]]
"""Shape: { employee_login: { "name": str, "role": str, "manager": str|None,
                                 "subordinates": list[str], "team": str } }"""


def load_org_graph(path: str) -> OrgGraph:
    """Load an organisational structure from a YAML file.

    The YAML must have an ``employees`` top-level key whose value is a list
    of employee dicts.  Each dict requires: ``login``, ``name``, ``role``,
    ``manager`` (or null), ``team``.

    Returns a dict keyed by *login* for O(1) lookups.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Org graph file not found: {path}")

    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    employees: list[dict] = raw.get("employees", [])
    graph: OrgGraph = {}

    for emp in employees:
        login = emp["login"]
        graph[login] = {
            "name": emp["name"],
            "role": emp.get("role", ""),
            "manager": emp.get("manager"),
            "subordinates": emp.get("subordinates", []),
            "team": emp.get("team", ""),
        }

    return graph


def check_authority(author: str, assignee: str, org_graph: OrgGraph) -> str:
    """Check whether *author* can assign work to *assignee*.

    Returns one of the four status strings documented at module level.
    """
    if author not in org_graph:
        return "invalid_authority"
    if assignee not in org_graph:
        return "invalid_authority"

    a_emp = org_graph[author]
    b_emp = org_graph[assignee]

    # Direct manager -> subordinate
    if assignee in a_emp.get("subordinates", []):
        return "valid"

    # Subordinate -> manager
    if author in b_emp.get("subordinates", []):
        return "invalid_subordinate_to_manager"

    # Same team but different hierarchy level (e.g. skip-level)
    if a_emp.get("team") == b_emp.get("team"):
        # Traverse up the chain from assignee to see if author is a higher-level manager
        visited: set[str] = set()
        cursor = b_emp.get("manager")
        while cursor and cursor not in visited:
            if cursor == author:
                return "valid"
            visited.add(cursor)
            parent = org_graph.get(cursor)
            if parent is None:
                break
            cursor = parent.get("manager")

    # Cross-functional — different teams
    if a_emp.get("team") != b_emp.get("team"):
        # Author must have management standing (subordinates) for cross-functional
        if a_emp.get("subordinates"):
            return "cross_functional"
        return "invalid_authority"

    # Fallback
    return "invalid_authority"


def find_subordinates(login: str, org_graph: OrgGraph, *, depth: int = 1) -> list[str]:
    """Return the list of direct (and optionally indirect) subordinates.

    Args:
        login: Employee login to start from.
        org_graph: Loaded org structure.
        depth: How many levels deep to traverse.  -1 = unlimited.

    Returns:
        Flat list of login strings.
    """
    if login not in org_graph:
        return []

    result: list[str] = []
    queue: list[tuple[str, int]] = [(login, 0)]

    while queue:
        current, level = queue.pop(0)
        if depth != -1 and level >= depth:
            continue
        emp = org_graph.get(current)
        if emp is None:
            continue
        for sub in emp.get("subordinates", []):
            result.append(sub)
            queue.append((sub, level + 1))

    return result


def find_manager_chain(login: str, org_graph: OrgGraph) -> list[str]:
    """Return the management chain from *login* up to the top, exclusive.

    Example: [login's manager, skip-level manager, ..., CEO]
    """
    chain: list[str] = []
    visited: set[str] = set()
    emp = org_graph.get(login)
    if emp is None:
        return chain

    cursor = emp.get("manager")
    while cursor and cursor not in visited:
        chain.append(cursor)
        visited.add(cursor)
        parent = org_graph.get(cursor)
        if parent is None:
            break
        cursor = parent.get("manager")

    return chain

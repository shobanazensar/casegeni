from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

TEST_CASE_SCHEMA_DEFAULTS = {
    "test_case_id": "",
    "story_id": "",
    "story_title": "",
    "ac_id": "",
    "ac_text": "",
    "title": "",
    "domain": "",
    "module": "",
    "submodule": "",
    "test_case_layer": "UI",
    "scenario_type": "Positive",
    "functional_test_type": "Functional",
    "non_functional_type": "",
    "priority": "P3",
    "automation_hint": "May be",
    "automated": "May be",
    "preconditions": [],
    "test_data": [],
    "steps": [],
    "expected_result": "",
    "tags": [],
    "risk_tags": [],
    "review_feedback": [],
    "review_profile": "",
    "reviewer_grade": "",
    "reviewer_score": 0.0,
    "suite": "Regression",
}

VALID_LAYERS = {"UI", "API", "Database", "ETL Integration", "E2E"}
VALID_SCENARIO_TYPES = {"Positive", "Negative", "Edge Case", "Exception Handling"}
VALID_FUNCTIONAL_TYPES = {"Functional", "Smoke", "Sanity", "Regression", ""}
VALID_NON_FUNCTIONAL_TYPES = {"Performance", "Security", "Accessibility", "Compatibility", ""}
VALID_PRIORITIES = {"P1", "P2", "P3", "P4"}
VALID_AUTOMATED = {"Yes", "No", "May be", "Maybe"}


def _ensure_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _ensure_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _normalize_list_of_strings(values: Any) -> list[str]:
    items = []
    for item in _ensure_list(values):
        if item is None:
            continue
        if isinstance(item, dict):
            text = json.dumps(item, ensure_ascii=False)
        else:
            text = str(item).strip()
        if text:
            items.append(text)
    return items


def _norm_set(value: Any, allowed: set[str], default: str, aliases: dict[str, str] | None = None) -> str:
    text = _ensure_string(value)
    if text in allowed:
        return text
    aliases = aliases or {}
    return aliases.get(text.lower(), default)


def apply_schema_guardrail(test_case: dict, index: int = 0) -> dict:
    tc = deepcopy(TEST_CASE_SCHEMA_DEFAULTS)
    tc.update(test_case or {})

    tc["test_case_id"] = _ensure_string(tc.get("test_case_id")) or f"TC{index+1:05d}"
    tc["story_id"] = _ensure_string(tc.get("story_id"))
    tc["story_title"] = _ensure_string(tc.get("story_title")) or tc["story_id"] or f"Story {index+1}"
    tc["ac_id"] = _ensure_string(tc.get("ac_id"))
    tc["ac_text"] = _ensure_string(tc.get("ac_text"))
    tc["title"] = _ensure_string(tc.get("title")) or f"{tc['scenario_type']} validation for {tc['ac_id'] or tc['story_id']}"
    tc["domain"] = _ensure_string(tc.get("domain"))
    tc["module"] = _ensure_string(tc.get("module"))
    tc["submodule"] = _ensure_string(tc.get("submodule"))
    tc["test_case_layer"] = _norm_set(tc.get("test_case_layer"), VALID_LAYERS, "UI", {
        "db": "Database", "database": "Database", "etl": "ETL Integration", "integration": "ETL Integration", "ui": "UI", "api": "API", "e2e": "E2E", "end to end": "E2E"
    })
    tc["scenario_type"] = _norm_set(tc.get("scenario_type"), VALID_SCENARIO_TYPES, "Positive", {
        "positive": "Positive", "negative": "Negative", "edge": "Edge Case", "edge case": "Edge Case", "exception": "Exception Handling", "exception handling": "Exception Handling"
    })
    tc["functional_test_type"] = _norm_set(tc.get("functional_test_type"), VALID_FUNCTIONAL_TYPES, "Functional", {
        "functional": "Functional", "smoke": "Smoke", "sanity": "Sanity", "regression": "Regression"
    })
    tc["non_functional_type"] = _norm_set(tc.get("non_functional_type"), VALID_NON_FUNCTIONAL_TYPES, "", {
        "performance": "Performance", "security": "Security", "accessibility": "Accessibility", "compatibility": "Compatibility"
    })
    tc["priority"] = _norm_set(tc.get("priority"), VALID_PRIORITIES, "P3", {"critical": "P1", "high": "P2", "medium": "P3", "low": "P4"})
    automated = _ensure_string(tc.get("automated") or tc.get("automation_hint") or "May be")
    tc["automation_hint"] = _norm_set(automated, VALID_AUTOMATED, "May be", {"maybe": "May be", "yes": "Yes", "no": "No"})
    tc["automated"] = tc["automation_hint"]
    tc["expected_result"] = _ensure_string(tc.get("expected_result"))
    tc["preconditions"] = _normalize_list_of_strings(tc.get("preconditions"))
    tc["test_data"] = _normalize_list_of_strings(tc.get("test_data"))
    tc["steps"] = _normalize_list_of_strings(tc.get("steps"))
    tc["tags"] = _normalize_list_of_strings(tc.get("tags"))
    tc["risk_tags"] = _normalize_list_of_strings(tc.get("risk_tags"))
    tc["review_feedback"] = _normalize_list_of_strings(tc.get("review_feedback"))
    tc["review_profile"] = _ensure_string(tc.get("review_profile"))
    tc["reviewer_grade"] = _ensure_string(tc.get("reviewer_grade"))
    try:
        tc["reviewer_score"] = float(tc.get("reviewer_score") or 0.0)
    except Exception:
        tc["reviewer_score"] = 0.0
    tc["suite"] = _ensure_string(tc.get("suite") or "Regression")
    return tc


def apply_schema_guardrail_bulk(test_cases: list[dict]) -> list[dict]:
    return [apply_schema_guardrail(tc, i) for i, tc in enumerate(test_cases or [])]

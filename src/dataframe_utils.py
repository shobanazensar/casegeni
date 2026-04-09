from __future__ import annotations

import json
import pandas as pd
from typing import Any

DISPLAY_COLUMNS = [
    "test_case_id", "story_id", "ac_id", "title", "domain", "module", "test_case_layer",
    "scenario_type", "test_suite", "execution_tags",
    "priority", "automated",
    "preconditions", "test_data", "steps", "expected_result",
]

CAMEL_CASE_HEADERS = {
    "test_case_id": "TestCaseId",
    "story_id": "StoryId",
    "ac_id": "AcId",
    "title": "Title",
    "domain": "Domain",
    "module": "Module",
    "test_case_layer": "TestCaseLayer",
    "scenario_type": "ScenarioType",
    "test_suite": "TestSuite",
    "execution_tags": "ExecutionTags",
    "priority": "Priority",
    "automated": "Automated",
    "preconditions": "Preconditions",
    "test_data": "TestData",
    "steps": "Steps",
    "expected_result": "ExpectedResult",
}


def normalize_cell_for_dataframe(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def test_cases_to_dataframe(test_cases: list[dict]) -> pd.DataFrame:
    rows = []
    for tc in test_cases or []:
        row = {k: normalize_cell_for_dataframe(v) for k, v in tc.items() if k in DISPLAY_COLUMNS}
        rows.append(row)
    df = pd.DataFrame(rows)
    for col in DISPLAY_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[DISPLAY_COLUMNS]
    return df.rename(columns=CAMEL_CASE_HEADERS)

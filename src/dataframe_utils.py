from __future__ import annotations

import json
import pandas as pd
from typing import Any

DISPLAY_COLUMNS = [
    "test_case_id", "story_id", "ac_id", "title", "domain", "module", "test_case_layer",
    "scenario_type", "functional_test_type", "non_functional_type", "priority", "automated",
    "suite", "preconditions", "test_data", "steps", "expected_result", "reviewer_grade", "reviewer_score"
]

CAMEL_CASE_HEADERS = {
    "test_case_id": "testCaseId",
    "story_id": "storyId",
    "ac_id": "acId",
    "title": "title",
    "domain": "domain",
    "module": "module",
    "test_case_layer": "testCaseLayer",
    "scenario_type": "scenarioType",
    "functional_test_type": "functionalTestType",
    "non_functional_type": "nonFunctionalType",
    "priority": "priority",
    "automated": "automated",
    "suite": "suite",
    "preconditions": "preconditions",
    "test_data": "testData",
    "steps": "steps",
    "expected_result": "expectedResult",
    "reviewer_grade": "reviewerGrade",
    "reviewer_score": "reviewerScore",
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

from __future__ import annotations
from src.agents.base import AgentBase


class A6Prioritization(AgentBase):
    def __init__(self, base_dir):
        super().__init__(base_dir, "A6 Prioritization - Offline.updated.json")

    def execute(self, test_cases: list[dict], project_state: str) -> dict:
        for tc in test_cases:
            risk = 0
            ac = tc["ac_text"].lower()
            if tc["scenario_type"] == "Negative":
                risk += 1
            if tc["scenario_type"] == "Exception Handling":
                risk += 2
            if tc["test_case_layer"] in {"API", "E2E", "ETL Integration"}:
                risk += 1
            if any(k in ac for k in ["unauthorized", "permission", "security", "payment", "audit", "mandatory", "state transition"]):
                risk += 2
            if project_state == "Legacy":
                risk += 1

            if risk >= 4:
                priority = "P1"
            elif risk == 3:
                priority = "P2"
            elif risk == 2:
                priority = "P3"
            else:
                priority = "P4"

            tc["priority"] = priority
            tc["automation_hint"] = "Yes" if tc["test_case_layer"] in {"API", "Database", "ETL Integration"} else ("Maybe" if tc["test_case_layer"] in {"UI", "E2E"} else "No")
            tc["automated"] = tc["automation_hint"]
        return {"test_cases": test_cases}

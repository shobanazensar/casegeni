from __future__ import annotations
from src.agents.base import AgentBase


class A7Optimization(AgentBase):
    def __init__(self, base_dir):
        super().__init__(base_dir, "A7 Optimization - Offline.updated.json")

    def execute(self, test_cases: list[dict], max_test_count: int) -> dict:
        before = len(test_cases)
        deduped = []
        seen = set()
        for tc in test_cases:
            key = (tc["story_id"], tc["ac_id"], tc["scenario_type"], tc["test_case_layer"], tc.get("expected_result", "").lower()[:120])
            if key not in seen:
                deduped.append(tc)
                seen.add(key)

        def rank(tc: dict) -> tuple:
            priority_rank = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}.get(tc.get("priority", "P3"), 2)
            suite_rank = 0 if tc.get("functional_test_type") == "Smoke" else 1
            layer_rank = {"API": 0, "UI": 1, "Database": 2, "E2E": 3, "ETL Integration": 4}.get(tc.get("test_case_layer"), 5)
            return (tc.get("story_id", ""), tc.get("ac_id", ""), priority_rank, suite_rank, layer_rank, tc.get("title", ""))

        optimized = sorted(deduped, key=rank)[:max_test_count]
        for tc in optimized:
            tc["suite"] = "Smoke" if tc.get("functional_test_type") == "Smoke" or tc.get("priority") == "P1" else "Regression"

        p12 = [x for x in deduped if x.get("priority") in {"P1", "P2"}]
        return {
            "test_cases_before_optimization": test_cases,
            "test_cases_after_optimization": optimized,
            "optimization_summary": {
                "tests_removed": max(0, before - len(optimized)),
                "reduction_percent": round(((before - len(optimized)) / before) * 100, 2) if before else 0,
                "smoke_count": sum(1 for x in optimized if x["suite"] == "Smoke"),
                "regression_count": sum(1 for x in optimized if x["suite"] == "Regression"),
                "critical_coverage_preserved": "Yes" if all(any(o["test_case_id"] == p["test_case_id"] for o in optimized) for p in p12[: min(len(p12), len(optimized))]) else "No",
            },
        }

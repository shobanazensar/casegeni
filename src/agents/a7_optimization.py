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

        _SCENARIO_ORDER = {"Positive": 0, "Smoke": 0, "Sanity": 1, "Negative": 2, "Edge Case": 3, "Exception Handling": 4}
        _LAYER_ORDER = {"UI": 0, "API": 1, "Database": 2, "ETL": 3}

        def rank(tc: dict) -> tuple:
            scenario_rank = _SCENARIO_ORDER.get(tc.get("scenario_type", ""), 5)
            layer_rank = _LAYER_ORDER.get(tc.get("test_case_layer", ""), 5)
            priority_rank = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}.get(tc.get("priority", "P3"), 2)
            return (tc.get("story_id", ""), tc.get("ac_id", ""), scenario_rank, layer_rank, priority_rank, tc.get("title", ""))

        optimized = sorted(deduped, key=rank)[:max_test_count]
        for tc in optimized:
            # Preserve test_suite if already set by A5 LLM; default to Functional
            ts = tc.get("test_suite", "")
            if ts not in {"Smoke", "Functional", "EndToEnd"}:
                ts = "Functional"
            tc["test_suite"] = ts
            tc["suite"] = ts  # backward-compat alias
            # Ensure execution_tags default to Regression if not already assigned
            if not tc.get("execution_tags"):
                tc["execution_tags"] = ["Regression"]

        p12 = [x for x in deduped if x.get("priority") in {"P1", "P2"}]
        return {
            "test_cases_before_optimization": test_cases,
            "test_cases_after_optimization": optimized,
            "optimization_summary": {
                "tests_removed": max(0, before - len(optimized)),
                "reduction_percent": round(((before - len(optimized)) / before) * 100, 2) if before else 0,
                "smoke_count": sum(1 for x in optimized if x.get("test_suite") == "Smoke"),
                "functional_count": sum(1 for x in optimized if x.get("test_suite") == "Functional"),
                "endtoend_count": sum(1 for x in optimized if x.get("test_suite") == "EndToEnd"),
                "critical_coverage_preserved": "Yes" if all(any(o["test_case_id"] == p["test_case_id"] for o in optimized) for p in p12[: min(len(p12), len(optimized))]) else "No",
            },
        }

from __future__ import annotations
from src.agents.base import AgentBase


CATEGORY_ICON = {
    "Functional": "🔵 FUNC",
    "Smoke": "🔵 FUNC",
    "Sanity": "🔵 FUNC",
    "Regression": "🔵 FUNC",
    "Performance": "🔴 NF",
    "Security": "🔴 NF",
    "Accessibility": "🔴 NF",
    "Compatibility": "🔴 NF",
    "API": "🟢 API",
    "ETL Integration": "🟠 ETL",
    "Database": "🟣 DB",
    "E2E": "🟤 E2E",
    "UI": "🔵 FUNC",
}
AUTO_ICON = {"Yes": "✅", "No": "❌", "May be": "⚠️", "Maybe": "⚠️"}


class A8Traceability(AgentBase):
    def __init__(self, base_dir):
        super().__init__(base_dir, "A8 Traceability - Offline.updated.json")

    def _category(self, tc: dict) -> str:
        if tc.get("non_functional_type"):
            return CATEGORY_ICON.get(tc.get("non_functional_type"), "🔴 NF")
        return CATEGORY_ICON.get(tc.get("test_case_layer"), "🔵 FUNC")

    def execute(self, requirements: list[dict], test_cases: list[dict]) -> dict:
        matrix = []
        readable_rows = []
        covered = 0
        uncovered = []
        by_req = {(str(tc.get("story_id", "")).strip(), str(tc.get("ac_id", "")).strip()): [] for tc in test_cases}
        for tc in test_cases:
            by_req.setdefault((str(tc.get("story_id", "")).strip(), str(tc.get("ac_id", "")).strip()), []).append(tc)

        for req in requirements:
            key = (str(req["story_id"]).strip(), str(req["ac_id"]).strip())
            mapped = by_req.get(key, [])
            if mapped:
                covered += 1
            else:
                uncovered.append(req)
            matrix.append({
                "story_id": req["story_id"],
                "story_title": req["story_title"],
                "ac_id": req["ac_id"],
                "ac_text": req["text"],
                "mapped_test_cases": [tc["test_case_id"] for tc in mapped],
                "coverage": "Covered" if mapped else "Gap",
            })

            groups = {}
            for tc in mapped:
                cat = self._category(tc)
                groups.setdefault(cat, []).append(tc)

            if not groups:
                readable_rows.append({
                    "storyId": req["story_id"], "acId": req["ac_id"], "testCaseIds": "", "category": "", "priority": "", "auto": "", "coverage": "Gap", "domain": "", "gapsNotes": "No mapped test case"
                })
                continue

            for category, items in groups.items():
                priorities = "/".join(sorted(set(tc.get("priority", "") for tc in items if tc.get("priority"))))
                auto = "/".join(sorted(set(AUTO_ICON.get(tc.get("automated", "May be"), "⚠️") for tc in items)))
                coverage = ", ".join(sorted(set(tc.get("scenario_type") if not tc.get("non_functional_type") else tc.get("non_functional_type") for tc in items if tc.get("scenario_type") or tc.get("non_functional_type"))))
                notes = []
                if all(tc.get("scenario_type") != "Negative" for tc in items) and all(tc.get("non_functional_type") != "Security" for tc in items):
                    notes.append("Missing negative or risk-focused coverage")
                if category in {"🔵 FUNC", "🟢 API", "🟣 DB"} and all(tc.get("scenario_type") != "Edge Case" for tc in items):
                    notes.append("Missing edge coverage")
                readable_rows.append({
                    "storyId": req["story_id"],
                    "acId": req["ac_id"],
                    "testCaseIds": ", ".join(tc["test_case_id"] for tc in items),
                    "category": category,
                    "priority": priorities,
                    "auto": auto,
                    "coverage": coverage,
                    "domain": items[0].get("domain", ""),
                    "gapsNotes": "; ".join(notes),
                })

        summary = {
            "total_acs": len(requirements),
            "covered_acs": covered,
            "traceability_coverage_percent": round((covered / len(requirements)) * 100, 2) if requirements else 0.0,
            "uncovered_count": len(uncovered),
        }
        return {"traceability_matrix": matrix, "traceability_summary": summary, "traceability_readable": readable_rows, "uncovered_items": uncovered}

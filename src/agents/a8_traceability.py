from __future__ import annotations
from src.agents.base import AgentBase


AUTO_ICON = {"Yes": "✅", "No": "❌", "May be": "⚠️", "Maybe": "⚠️"}


class A8Traceability(AgentBase):
    def __init__(self, base_dir):
        super().__init__(base_dir, "A8 Traceability - Offline.updated.json")

    def execute(self, requirements: list[dict], test_cases: list[dict], removed_by_ac: dict | None = None) -> dict:
        matrix = []
        readable_rows = []
        covered = 0
        uncovered = []
        removed_by_ac = removed_by_ac or {}

        by_req: dict = {}
        for tc in test_cases:
            key = (str(tc.get("story_id", "")).strip(), str(tc.get("ac_id", "")).strip())
            by_req.setdefault(key, []).append(tc)

        for req in requirements:
            key = (str(req["story_id"]).strip(), str(req["ac_id"]).strip())
            mapped = by_req.get(key, [])
            if mapped:
                covered += 1
            else:
                uncovered.append(req)

            removed = removed_by_ac.get(str(req["ac_id"]).strip(), [])

            matrix.append({
                "story_id": req["story_id"],
                "story_title": req["story_title"],
                "ac_id": req["ac_id"],
                "ac_text": req["text"],
                "mapped_test_cases": [tc["test_case_id"] for tc in mapped],
                "removed_test_cases": removed,
                "coverage": "Covered" if mapped else "Gap",
            })

            if not mapped:
                readable_rows.append({
                    "storyId": req["story_id"],
                    "acId": req["ac_id"],
                    "acText": req["text"][:120],
                    "testCaseId": "",
                    "title": "",
                    "testCaseLayer": "",
                    "scenarioType": "",
                    "testSuite": "",
                    "nonFunctionalType": "",
                    "priority": "",
                    "automatable": "",
                    "coverage": "Gap",
                    "gapNotes": "No test case mapped to this AC",
                })
                continue

            # ── AC-level gap analysis (computed once across all TCs for this AC) ──
            all_scenario_types = {tc.get("scenario_type", "") for tc in mapped}
            all_nf_types = {tc.get("non_functional_type", "") for tc in mapped}
            ac_gap_notes = []
            if "Negative" not in all_scenario_types and "Security" not in all_nf_types:
                ac_gap_notes.append("Missing negative/risk coverage")
            if "Edge Case" not in all_scenario_types:
                ac_gap_notes.append("Missing edge case coverage")

            # ── One row per test case ──────────────────────────────────────────
            for tc in mapped:
                readable_rows.append({
                    "storyId": tc.get("story_id", req["story_id"]),
                    "acId": tc.get("ac_id", req["ac_id"]),
                    "acText": req["text"][:120],
                    "testCaseId": tc.get("test_case_id", ""),
                    "title": tc.get("title", ""),
                    "testCaseLayer": tc.get("test_case_layer", ""),
                    "scenarioType": tc.get("scenario_type", ""),
                    "testType": tc.get("test_type", "Functional"),
                    "nonFunctionalType": tc.get("non_functional_type", ""),
                    "priority": tc.get("priority", ""),
                    "automatable": AUTO_ICON.get(tc.get("automated", "May be"), "⚠️"),
                    "coverage": "Covered",
                    "gapNotes": "; ".join(ac_gap_notes),
                })

        summary = {
            "total_acs": len(requirements),
            "covered_acs": covered,
            "traceability_coverage_percent": round((covered / len(requirements)) * 100, 2) if requirements else 0.0,
            "uncovered_count": len(uncovered),
        }
        return {
            "traceability_matrix": matrix,
            "traceability_summary": summary,
            "traceability_readable": readable_rows,
            "uncovered_items": uncovered,
        }

from __future__ import annotations
from collections import Counter
from src.agents.base import AgentBase


class A10Dashboard(AgentBase):
    def __init__(self, base_dir):
        super().__init__(base_dir, "A10 Dashboard - Offline.updated.json")

    def execute(
        self,
        test_cases_before_optimization: list[dict],
        test_cases_after_optimization: list[dict],
        traceability_summary: dict,
        uncovered_items: list[dict],
        review_summary: dict,
        optimization_summary: dict,
    ) -> dict:
        after = test_cases_after_optimization
        by_layer = Counter(x["test_case_layer"] for x in after)
        by_scenario = Counter(x["scenario_type"] for x in after)
        by_priority = Counter(x["priority"] for x in after)

        ac_ids = {x["ac_id"] for x in after}
        all_acs = traceability_summary.get("total_acs", 0)
        acs_without_tests = traceability_summary.get("uncovered_count", 0)
        ac_missing_negative = 0
        ac_missing_edge = 0
        grouped = {}
        for tc in after:
            grouped.setdefault(tc["ac_id"], []).append(tc)
        for ac_id, tests in grouped.items():
            scenarios = {x["scenario_type"] for x in tests}
            if "Negative" not in scenarios:
                ac_missing_negative += 1
            if "Edge Case" not in scenarios:
                ac_missing_edge += 1

        automation_yes = sum(1 for x in after if x["automation_hint"] == "Yes")
        coverage = traceability_summary.get("traceability_coverage_percent", 0)
        review_score = review_summary.get("avg_reviewer_score", 0)
        automation_readiness = round((automation_yes / len(after)) * 100, 2) if after else 0
        quality_score = round((review_score * 14) + (coverage * 0.3) - (acs_without_tests * 5), 2)
        if acs_without_tests > 0 or coverage < 80:
            readiness = "At Risk"
        elif review_score < 3.8:
            readiness = "Needs Review"
        else:
            readiness = "Ready"

        top_recommendations = []
        if acs_without_tests:
            top_recommendations.append("Add tests for uncovered acceptance criteria first.")
        if ac_missing_negative:
            top_recommendations.append("Strengthen negative-path coverage for uncovered AC patterns.")
        if ac_missing_edge:
            top_recommendations.append("Increase edge/boundary coverage for critical validations.")
        if not top_recommendations:
            top_recommendations = ["Maintain current coverage baseline.", "Promote smoke suite into CI gate.", "Track reviewer score drift over time."]

        dashboard = {
            "summary": {
                "total_acs": all_acs,
                "total_tests_before": len(test_cases_before_optimization),
                "total_tests_after": len(test_cases_after_optimization),
                "reduction_percent": optimization_summary.get("reduction_percent", 0),
                "traceability_coverage_percent": coverage,
                "avg_reviewer_score": review_score,
                "automation_readiness_percent": automation_readiness,
            },
            "coverage_snapshot": {
                "by_layer": dict(by_layer),
                "by_scenario_type": dict(by_scenario),
                "by_priority": dict(by_priority),
            },
            "optimization_impact": optimization_summary,
            "quality_gaps": {
                "acs_without_tests": acs_without_tests,
                "acs_missing_negative": ac_missing_negative,
                "acs_missing_edge": ac_missing_edge,
                "tests_needing_human_review": len(review_summary.get("tests_needing_human_review", [])),
                "low_quality_tests": review_summary.get("grades", {}).get("Poor", 0),
            },
            "final_verdict": {
                "overall_quality_score": quality_score,
                "release_readiness": readiness,
                "top_recommendations": top_recommendations[:3],
            },
        }
        return dashboard

    def to_html(self, dashboard: dict) -> str:
        s = dashboard["summary"]
        verdict = dashboard["final_verdict"]
        return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<title>Test Intelligence Dashboard</title>
<style>
body {{ font-family: Arial, sans-serif; background:#f7faff; color:#0f2640; margin:0; padding:24px; }}
h1, h2 {{ color:#0f3d75; }}
.grid {{ display:grid; grid-template-columns: repeat(4, 1fr); gap:16px; margin-bottom:24px; }}
.card {{ background:white; border:1px solid #d7e4f7; border-radius:14px; padding:16px; box-shadow:0 2px 8px rgba(15,61,117,0.06); }}
.label {{ font-size:12px; color:#4a6280; text-transform:uppercase; }}
.value {{ font-size:28px; font-weight:700; margin-top:8px; }}
ul {{ margin-top:8px; }}
pre {{ background:white; border:1px solid #d7e4f7; padding:12px; border-radius:12px; }}
</style>
</head>
<body>
<h1>Test Intelligence Dashboard</h1>
<div class="grid">
  <div class="card"><div class="label">Tests After Optimization</div><div class="value">{s['total_tests_after']}</div></div>
  <div class="card"><div class="label">Coverage %</div><div class="value">{s['traceability_coverage_percent']}</div></div>
  <div class="card"><div class="label">Reviewer Score</div><div class="value">{s['avg_reviewer_score']}</div></div>
  <div class="card"><div class="label">Automation Readiness %</div><div class="value">{s['automation_readiness_percent']}</div></div>
</div>
<div class="card">
<h2>Release Readiness: {verdict['release_readiness']}</h2>
<p><strong>Quality Score:</strong> {verdict['overall_quality_score']}</p>
<ul>{''.join(f'<li>{x}</li>' for x in verdict['top_recommendations'])}</ul>
</div>
<div class="card"><h2>Dashboard JSON</h2><pre>{dashboard}</pre></div>
</body></html>
"""

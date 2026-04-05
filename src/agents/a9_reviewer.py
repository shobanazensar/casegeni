from __future__ import annotations
from collections import Counter, defaultdict
from statistics import mean
from src.agents.base import AgentBase


class A9Reviewer(AgentBase):
    def __init__(self, base_dir):
        super().__init__(base_dir, "A9 Reviewer - Offline.updated.json")
        self.profiles = self.config.get("review_profiles", {})
        self.allowed_layers = set(self.config.get("schema_rules", {}).get("allowed_test_case_layers", []))

    def _profile_for(self, tc: dict) -> str:
        if tc.get("non_functional_type"):
            return "NonFunctional"
        return {
            "UI": "UI_Business",
            "API": "API",
            "Database": "Database",
            "ETL Integration": "ETL_Integration",
            "E2E": "E2E_BusinessFlow",
        }.get(tc.get("test_case_layer"), "UI_Business")

    def _has_keywords(self, text: str, words: list[str]) -> bool:
        text = text.lower()
        return any(w in text for w in words)

    def _score_dimension(self, tc: dict, dimension: str, mapped_ac_ids: set[str]) -> tuple[float, str]:
        layer = tc.get("test_case_layer", "")
        title = tc.get("title", "")
        steps_text = " ".join(tc.get("steps", []))
        expected = tc.get("expected_result", "")
        scenario = tc.get("scenario_type", "")
        non_func = tc.get("non_functional_type", "")
        all_text = f"{title} {steps_text} {expected}".lower()

        # default baseline
        score = 3.0
        reasons = []

        if dimension == "traceability":
            score = 5.0 if tc.get("ac_id") in mapped_ac_ids and tc.get("story_id") else 2.5
            reasons.append("Strong traceability" if score >= 4.5 else "Traceability metadata is weak")
        elif dimension == "clarity":
            score = 4.8 if len(title) >= 25 and len(tc.get("steps", [])) >= 3 else 3.0
            if "|" in title:
                score -= 1.0
                reasons.append("Template-style title hurts clarity")
            # Penalise titles that are too generic
            vague_title_phrases = ["validate ac", "test ac", "verify ac", "check ac", "positive test", "negative test"]
            if any(p in title.lower() for p in vague_title_phrases):
                score -= 1.5
                reasons.append("Title is too generic — must describe the specific outcome being verified")
            reasons.append("Steps are readable and specific" if score >= 4.0 else "Needs clearer title or steps")
        elif dimension == "correctness":
            score = 4.5 if expected and len(expected) >= 35 else 3.0
            # Penalise vague expected results
            vague_expected = ["system works as expected", "no issues observed", "correctly", "should be correct", "as expected", "the business rule is satisfied"]
            if any(p in expected.lower() for p in vague_expected):
                score -= 2.0
                reasons.append("Expected result is too vague — must be specific, measurable, and assertable")
            if layer == "API" and self._has_keywords(all_text, ["screen", "page", "click"]):
                score -= 1.2
                reasons.append("API case uses UI-only language")
            if layer == "Database" and not self._has_keywords(all_text, ["query", "table", "persist", "audit", "history", "stored"]):
                score -= 1.0
                reasons.append("Database verification detail is weak")
            if layer == "ETL Integration" and not self._has_keywords(all_text, ["payload", "mapping", "downstream", "reconciliation", "retry", "transform"]):
                score -= 1.0
                reasons.append("Integration flow evidence is weak")
            reasons.append("Layer behavior is largely correct" if score >= 4.0 else "Layer expectations need tightening")
        elif dimension == "completeness":
            preconds = tc.get("preconditions", [])
            steps_list = tc.get("steps", [])
            test_data_list = tc.get("test_data", [])
            score = 5.0 if len(preconds) >= 2 and len(steps_list) >= 3 and expected and len(test_data_list) >= 2 else 2.8
            # Penalise vague preconditions
            vague_pre_phrases = ["user is logged in", "all configurations are correct", "valid business context", "system is available", "user has access"]
            vague_pre_count = sum(1 for p in preconds if any(v in p.lower() for v in vague_pre_phrases))
            if vague_pre_count > 0:
                score -= min(1.5, vague_pre_count * 0.75)
                reasons.append(f"{vague_pre_count} precondition(s) are vague — must specify system state and exact user role")
            # Penalise vague test data
            vague_data_phrases = ["valid data", "existing record", "any value", "use values relevant", "aligned to the scenario"]
            vague_data_count = sum(1 for d in test_data_list if any(v in str(d).lower() for v in vague_data_phrases))
            if vague_data_count > 0:
                score -= min(1.5, vague_data_count * 0.75)
                reasons.append(f"{vague_data_count} test data item(s) are vague — must provide specific concrete values")
            # Penalise steps that contain assertions
            assertion_steps = sum(1 for s in steps_list if any(v in s.lower() for v in ["verify", "check if", "ensure", "assert", "confirm that", "observe that"]))
            if assertion_steps > 0:
                score -= min(1.5, assertion_steps * 0.5)
                reasons.append(f"{assertion_steps} step(s) contain assertions — validations must go only in Expected Results")
            reasons.append("Has preconditions, steps, test data, and expected result" if score >= 4.5 else "Missing execution detail or contains quality violations")
        elif dimension == "business_outcome_focus":
            score = 4.5 if self._has_keywords(all_text, ["save", "updated", "blocked", "downstream", "audit", "customer", "profile", "business"]) else 3.0
            reasons.append("Outcome is business-observable" if score >= 4.0 else "Outcome is too generic")
        elif dimension == "defect_detection":
            score = 4.5 if scenario in {"Negative", "Edge Case", "Exception Handling"} or non_func == "Security" else 3.8
            reasons.append("Designed to catch failures or misbehavior" if score >= 4.0 else "Primarily happy-path coverage")
        elif dimension == "actionability":
            score = 4.6 if len(tc.get("steps", [])) >= 3 and len(tc.get("test_data", [])) >= 2 else 3.0
            reasons.append("Execution is actionable" if score >= 4.0 else "Needs stronger data or step detail")
        elif dimension == "maintainability":
            score = 4.5 if len(title) < 130 and len(tc.get("steps", [])) <= 5 else 3.2
            reasons.append("Readable and maintainable" if score >= 4.0 else "Could be simplified")
        elif dimension == "diagnostic_value":
            score = 4.6 if self._has_keywords(all_text, ["status code", "error", "log", "payload", "audit", "response", "retry"]) else 3.0
            reasons.append("Provides diagnostic evidence" if score >= 4.0 else "Needs stronger diagnostics")
        elif dimension == "security_awareness":
            score = 4.8 if self._has_keywords(all_text, ["401", "403", "permission", "unauthorized", "token", "authentication"]) else 2.8
            reasons.append("Security checks are explicit" if score >= 4.0 else "Security evidence is limited")
        elif dimension == "reusability":
            score = 4.2 if tc.get("test_case_layer") in {"API", "Database", "ETL Integration"} else 3.6
            reasons.append("Reusable across data variations" if score >= 4.0 else "Somewhat scenario-specific")
        elif dimension == "data_integrity":
            score = 4.8 if self._has_keywords(all_text, ["persist", "stored", "audit", "old", "new", "before", "after", "unchanged"]) else 3.0
            reasons.append("Validates stored state or audit accuracy" if score >= 4.0 else "Data integrity checks are weak")
        elif dimension == "transformation_accuracy":
            score = 4.8 if self._has_keywords(all_text, ["payload", "mapping", "transform", "downstream", "format"]) else 3.0
            reasons.append("Validates transformed downstream values" if score >= 4.0 else "Transformation checks are weak")
        elif dimension == "risk_coverage":
            score = 4.8 if scenario in {"Negative", "Exception Handling", "Edge Case"} or non_func in {"Performance", "Security"} else 3.2
            reasons.append("Covers important risk patterns" if score >= 4.0 else "Risk coverage is moderate")
        elif dimension == "measurement_clarity":
            score = 4.8 if self._has_keywords(all_text, ["sla", "latency", "throughput", "error rate", "window", "metric"]) else 2.8
            reasons.append("Measurement target is clear" if score >= 4.0 else "Measurement criteria are vague")
        elif dimension == "environment_readiness":
            score = 4.2 if self._has_keywords(all_text, ["environment", "load", "downstream", "screen-reader", "keyboard", "outage"]) else 3.0
            reasons.append("Environment prerequisites are acknowledged" if score >= 4.0 else "Environment needs are under-specified")
        else:
            reasons.append("Default scoring applied")
        return max(0.0, min(5.0, round(score, 2))), "; ".join(reasons)

    def _offline_review_one(self, tc: dict, mapped_ac_ids: set[str]) -> dict:
        profile = self._profile_for(tc)
        dimensions = self.profiles.get(profile, {}).get("dimensions", {})
        total_weight = sum(dimensions.values()) or 1
        scores = {}
        improvement_areas = []
        common_text = " ".join(tc.get("review_feedback", []))
        for dimension, weight in dimensions.items():
            dim_score, reason = self._score_dimension(tc, dimension, mapped_ac_ids)
            scores[dimension] = {"score": dim_score, "reason": reason, "weight": weight}
            if dim_score < 3.5:
                improvement_areas.append(f"{dimension}: {reason}")

        weighted = round(sum(v["score"] * v["weight"] for v in scores.values()) / total_weight, 2)
        if weighted >= 4.5:
            grade = "Excellent"
        elif weighted >= 3.5:
            grade = "Good"
        elif weighted >= 2.5:
            grade = "Acceptable"
        else:
            grade = "Poor"

        human_needed = weighted < 3.0 or not tc.get("expected_result") or tc.get("test_case_layer") not in self.allowed_layers
        summary_feedback = "; ".join(improvement_areas[:3]) if improvement_areas else "Quality is strong for the assigned layer."
        tc["review_profile"] = profile
        tc["reviewer_score"] = weighted
        tc["reviewer_grade"] = grade
        tc["review_feedback"] = improvement_areas[:5]
        tc["review_scores"] = scores
        tc["human_intervention_needed"] = human_needed
        tc["intervention_reason"] = "Low score or invalid classification" if human_needed else ""
        return tc

    def execute(self, test_cases: list[dict], reviewer_mode: str, llm_config: dict, traceability_summary: dict) -> dict:
        mapped_ac_ids = set(tc.get("ac_id") for tc in test_cases if tc.get("ac_id"))
        reviewed = [self._offline_review_one(dict(tc), mapped_ac_ids) for tc in test_cases]
        avg = round(mean([tc["reviewer_score"] for tc in reviewed]), 2) if reviewed else 0.0
        needs_human = [tc["test_case_id"] for tc in reviewed if tc.get("human_intervention_needed")]

        layer_scores, profile_scores = {}, {}
        for bucket_name, field in [(layer_scores, "test_case_layer"), (profile_scores, "review_profile")]:
            keys = sorted(set(tc.get(field, "") for tc in reviewed if tc.get(field, "")))
            for key in keys:
                vals = [tc["reviewer_score"] for tc in reviewed if tc.get(field) == key]
                bucket_name[key] = round(mean(vals), 2) if vals else 0.0

        common_issues = Counter(issue for tc in reviewed for issue in tc.get("review_feedback", []))
        reviewer_table = [{
            "testCaseId": tc["test_case_id"],
            "acId": tc["ac_id"],
            "title": tc["title"],
            "layer": tc.get("test_case_layer", ""),
            "profile": tc.get("review_profile", ""),
            "grade": tc["reviewer_grade"],
            "score": tc["reviewer_score"],
            "humanReview": "Yes" if tc.get("human_intervention_needed") else "No",
            "feedback": "; ".join(tc.get("review_feedback", [])),
        } for tc in reviewed]

        profile_dimension_summary = defaultdict(dict)
        for profile in sorted(set(tc.get("review_profile") for tc in reviewed if tc.get("review_profile"))):
            profile_cases = [tc for tc in reviewed if tc.get("review_profile") == profile]
            dims = self.profiles.get(profile, {}).get("dimensions", {})
            for dim in dims:
                vals = [tc.get("review_scores", {}).get(dim, {}).get("score", 0) for tc in profile_cases]
                profile_dimension_summary[profile][dim] = round(mean(vals), 2) if vals else 0.0

        return {
            "reviewed_test_cases": reviewed,
            "review_summary": {
                "avg_reviewer_score": avg,
                "grades": {g: sum(1 for t in reviewed if t["reviewer_grade"] == g) for g in ["Excellent", "Good", "Acceptable", "Poor"]},
                "tests_needing_human_review": needs_human,
                "traceability_coverage_percent": traceability_summary.get("traceability_coverage_percent", 0),
                "scores_by_layer": layer_scores,
                "scores_by_profile": profile_scores,
                "profile_dimension_summary": profile_dimension_summary,
                "major_common_issues": [f"{issue} ({count})" for issue, count in common_issues.most_common(8)],
                "reviewer_table": reviewer_table,
                "reviewer_mode_used": "offline_rules",
            },
        }

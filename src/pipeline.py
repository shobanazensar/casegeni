from __future__ import annotations
from pathlib import Path

from src.agents.a0_orchestrator import A0Orchestrator
from src.agents.a1_project_state import A1ProjectState
from src.agents.a2_domain_app import A2DomainApp
from src.agents.a3_requirements import A3Requirements
from src.agents.a4_scenario_derivation import A4ScenarioDerivation
from src.agents.a5_test_generation import A5TestGeneration
from src.agents.a6_prioritization import A6Prioritization
from src.agents.a7_optimization import A7Optimization
from src.agents.a8_traceability import A8Traceability
from src.agents.a9_reviewer import A9Reviewer
from src.agents.a10_dashboard import A10Dashboard
from src.utils.io_utils import dump_json, ensure_dir
from src.schema_guardrail import apply_schema_guardrail_bulk
from src.dataframe_utils import test_cases_to_dataframe


def _normalize_mode(value: str) -> str:
    value = (value or "").strip().lower()
    mapping = {"online": "online", "llm": "online", "offline": "offline", "rule": "offline", "rules": "offline"}
    return mapping.get(value, "offline")


class TestCasePipeline:
    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.a0 = A0Orchestrator()
        self.a1 = A1ProjectState()
        self.a2 = A2DomainApp(self.base_dir)
        self.a3 = A3Requirements(self.base_dir)
        self.a4 = A4ScenarioDerivation(self.base_dir)
        self.a5 = A5TestGeneration(self.base_dir)
        self.a6 = A6Prioritization(self.base_dir)
        self.a7 = A7Optimization(self.base_dir)
        self.a8 = A8Traceability(self.base_dir)
        self.a9 = A9Reviewer(self.base_dir)
        self.a10 = A10Dashboard(self.base_dir)

    def run(self, document_text: str, output_dir: str, execution_mode: str, reviewer_mode: str, selected_layers: list[str], selected_test_types: list[str], llm_config: dict, max_test_count: int) -> dict:
        execution_mode = _normalize_mode(execution_mode)
        reviewer_mode = _normalize_mode(reviewer_mode)
        llm_config = dict(llm_config or {})

        if execution_mode == "online":
            missing = [k for k in ["model", "base_url"] if not llm_config.get(k)]
            if missing:
                raise ValueError(f"Online mode selected but missing LLM configuration: {', '.join(missing)}")

        if reviewer_mode == "online":
            missing = [k for k in ["model", "base_url"] if not llm_config.get(k)]
            if missing:
                raise ValueError(f"Online reviewer mode selected but missing LLM configuration: {', '.join(missing)}")

        state = self.a0.execute(document_text, output_dir, execution_mode, reviewer_mode, selected_layers, selected_test_types, llm_config, max_test_count)
        state.update(self.a1.execute(document_text))
        state["domain_analysis"] = self.a2.execute(document_text, state["project_state"], state["state_driven_focus"])
        req = self.a3.execute(document_text)
        state.update(req)
        scn = self.a4.execute(req["requirements"], state["domain_analysis"], selected_layers, selected_test_types)
        state.update(scn)
        gen = self.a5.execute(scn["scenario_blueprints"], document_text, execution_mode, llm_config)
        gen["test_cases"] = apply_schema_guardrail_bulk(gen["test_cases"])
        state["llm_meta"] = gen.get("llm_meta", {})

        prior = self.a6.execute(gen["test_cases"], state["project_state"])
        state["test_cases_generated"] = apply_schema_guardrail_bulk(prior["test_cases"])
        opt = self.a7.execute(state["test_cases_generated"], max_test_count)
        opt["test_cases_after_optimization"] = apply_schema_guardrail_bulk(opt["test_cases_after_optimization"])
        state.update(opt)

        trace = self.a8.execute(req["requirements"], opt["test_cases_after_optimization"])
        state.update(trace)
        review = self.a9.execute(opt["test_cases_after_optimization"], reviewer_mode, llm_config, trace["traceability_summary"])
        state["test_cases"] = apply_schema_guardrail_bulk(review["reviewed_test_cases"])
        state["review_summary"] = review["review_summary"]

        _SCENARIO_ORDER = {"Positive": 0, "Smoke": 0, "Sanity": 1, "Negative": 2, "Edge Case": 3, "Exception Handling": 4}
        _LAYER_ORDER = {"UI": 0, "API": 1, "Database": 2, "ETL Integration": 3, "E2E": 4}
        state["test_cases"] = sorted(
            state["test_cases"],
            key=lambda x: (
                x.get("story_id", ""),
                x.get("ac_id", ""),
                _SCENARIO_ORDER.get(x.get("scenario_type", ""), 5),
                _LAYER_ORDER.get(x.get("test_case_layer", ""), 5),
                x.get("test_case_id", ""),
            ),
        )

        dashboard = self.a10.execute(
            test_cases_before_optimization=opt["test_cases_before_optimization"],
            test_cases_after_optimization=state["test_cases"],
            traceability_summary=trace["traceability_summary"],
            uncovered_items=trace["uncovered_items"],
            review_summary=state["review_summary"],
            optimization_summary=opt["optimization_summary"],
        )
        dashboard_html = self.a10.to_html(dashboard)
        artifact_dir = ensure_dir(state["artifact_dir"])

        run_config = {
            "execution_mode_requested": execution_mode,
            "execution_mode_used": "online" if state.get("llm_meta", {}).get("used") else "offline",
            "reviewer_mode_requested": reviewer_mode,
            "reviewer_mode_used": state["review_summary"].get("reviewer_mode_used", "offline_rules"),
            "selected_layers": selected_layers,
            "selected_test_types": selected_test_types,
            "llm_config": {**llm_config, "api_key": "***" if llm_config.get("api_key") else ""},
            "llm_meta": state.get("llm_meta", {}),
            "generator_source": state.get("llm_meta", {}).get("generator_source", "offline_rules"),
            "max_test_count": max_test_count,
        }

        manifest = {
            "project_state": state["project_state"],
            "state_driven_focus": state["state_driven_focus"],
            "domain_analysis": state["domain_analysis"],
            "requirements_summary": req["summary"],
            "run_config": run_config,
        }
        dump_json(artifact_dir / "manifest.json", manifest)
        dump_json(artifact_dir / "test_cases.json", state["test_cases"])
        dump_json(artifact_dir / "traceability.json", {"matrix": trace["traceability_matrix"], "summary": trace["traceability_summary"], "readable": trace["traceability_readable"]})
        dump_json(artifact_dir / "review_summary.json", state["review_summary"])
        dump_json(artifact_dir / "dashboard.json", dashboard)
        (artifact_dir / "dashboard.html").write_text(dashboard_html, encoding="utf-8")
        test_cases_df = test_cases_to_dataframe(state["test_cases"])
        test_cases_df.to_excel(artifact_dir / "test_cases.xlsx", index=False)

        return {
            "artifact_dir": str(artifact_dir),
            "test_cases": state["test_cases"],
            "traceability": {"matrix": trace["traceability_matrix"], "summary": trace["traceability_summary"], "readable": trace["traceability_readable"]},
            "review_summary": state["review_summary"],
            "dashboard": dashboard,
            "dashboard_html": dashboard_html,
            "test_cases_df": test_cases_df,
            "manifest": manifest,
        }

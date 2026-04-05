from __future__ import annotations
import json
from src.agents.base import AgentBase
from src.llm.client import LLMClient


class A4ScenarioDerivation(AgentBase):
    def __init__(self, base_dir):
        super().__init__(base_dir, "A4 Scenario Derivation - LLM.updated.json")

    def _layers_allowed(self, wanted: list[str], selected_layers: list[str]) -> list[str]:
        seen = []
        for layer in wanted:
            if layer in selected_layers and layer not in seen:
                seen.append(layer)
        return seen

    def _base_blueprint(self, req: dict, domain_context: dict, seed_type: str, focus: str, title_hint: str, layer: str, functional_type: str = "Functional", non_functional_type: str = "", scenario_key: str = "general") -> dict:
        module = domain_context["module_or_submodules"][0] if domain_context["module_or_submodules"] else "General"
        submodule = domain_context["module_or_submodules"][1] if len(domain_context["module_or_submodules"]) > 1 else ""
        return {
            "story_id": req["story_id"],
            "story_title": req["story_title"],
            "ac_id": req["ac_id"],
            "ac_text": req["text"],
            "domain": domain_context["primary_domain"],
            "module": module,
            "submodule": submodule,
            "seed_type": seed_type,
            "focus": focus,
            "title_hint": title_hint,
            "scenario_key": scenario_key,
            "layer_candidates": [layer],
            "functional_test_type": functional_type,
            "non_functional_type": non_functional_type,
            "risk_tags": [domain_context["project_state"].lower(), focus],
        }

    def _derive_for_requirement(self, req: dict, domain_context: dict, selected_layers: list[str], selected_test_types: list[str]) -> list[dict]:
        text = req["text"]
        text_l = text.lower()
        results = []
        add = results.append

        def add_if(layer: str, seed_type: str, focus: str, title_hint: str, scenario_key: str, functional_type: str = "Functional", non_functional_type: str = ""):
            if layer in selected_layers:
                add(self._base_blueprint(req, domain_context, seed_type, focus, title_hint, layer, functional_type, non_functional_type, scenario_key))

        if any(k in text_l for k in ["mandatory", "required", "must be provided", "cannot be blank", "blank"]):
            if "UI" in selected_layers:
                add_if("UI", "Positive", "business_valid_flow", "Update succeeds with all required fields populated", "ui_valid_required")
                add_if("UI", "Negative", "validation_or_rejection", "Blank required field is blocked with inline validation", "ui_required_blank")
            if "API" in selected_layers:
                add_if("API", "Negative", "validation_or_rejection", "API rejects request with missing required field", "api_missing_required")
            if "Database" in selected_layers:
                add_if("Database", "Negative", "data_integrity", "Rejected request does not persist partial data", "db_no_partial_persist")
            if any(k in text_l for k in ["trim", "spaces", "whitespace", "format", "length"]) and "UI" in selected_layers:
                add_if("UI", "Edge Case", "boundary_and_data_variation", "Whitespace and boundary handling for required fields", "ui_whitespace_boundary")

        if any(k in text_l for k in ["unique", "duplicate", "already used", "exists only on inactive", "email"]):
            if "UI" in selected_layers:
                add_if("UI", "Positive", "business_valid_flow", "Unique value is accepted in UI", "ui_unique_value")
                add_if("UI", "Negative", "validation_or_rejection", "Duplicate active value is blocked in UI", "ui_duplicate_active")
            if "API" in selected_layers:
                add_if("API", "Negative", "validation_or_rejection", "API rejects duplicate active value", "api_duplicate_active")
            if "Database" in selected_layers:
                add_if("Database", "Negative", "data_integrity", "Duplicate value is not persisted in master data", "db_duplicate_not_stored")
            if any(k in text_l for k in ["inactive", "active customers"]) and "UI" in selected_layers:
                add_if("UI", "Edge Case", "boundary_and_data_variation", "Inactive record rule is handled correctly", "ui_inactive_duplicate_rule")

        if any(k in text_l for k in ["unauthorized", "permission", "role", "forbidden", "authenticated", "unauthenticated"]):
            if "UI" in selected_layers:
                add_if("UI", "Negative", "authorization", "Unauthorized role cannot use edit action from UI", "ui_unauthorized_role", non_functional_type="Security")
            if "API" in selected_layers:
                add_if("API", "Negative", "authorization", "Unauthorized token is blocked by API", "api_unauthorized_token", non_functional_type="Security")
                add_if("API", "Exception Handling", "authentication", "Unauthenticated request is denied cleanly", "api_unauthenticated", non_functional_type="Security")
            if "ETL" in selected_layers and "Security" in selected_test_types:
                add_if("ETL", "Negative", "authorization", "Direct backend or integration bypass is denied", "integration_bypass_denied", non_functional_type="Security")

        if any(k in text_l for k in ["audit", "history", "previous and new values", "timestamp", "changed fields"]):
            if "UI" in selected_layers:
                add_if("UI", "Positive", "auditability", "Successful update creates visible audit history", "ui_audit_created")
            if "Database" in selected_layers:
                add_if("Database", "Positive", "auditability", "Audit record stores old and new values correctly", "db_audit_old_new")
                add_if("Database", "Edge Case", "auditability", "Only changed fields are marked as changed", "db_audit_changed_fields")
                add_if("Database", "Negative", "auditability", "Failed update does not create successful audit record", "db_no_audit_for_failed")

        if any(k in text_l for k in ["downstream", "sync", "etl", "integration", "crm", "mapping", "reconciliation", "transform"]):
            if "ETL" in selected_layers:
                add_if("ETL", "Positive", "integration_flow", "Successful update is propagated downstream", "etl_sync_success")
                add_if("ETL", "Edge Case", "integration_flow", "Outbound payload carries approved transformed values", "etl_payload_transform")
                add_if("ETL", "Exception Handling", "failure_recovery", "Downstream failure is logged for retry or exception handling", "etl_downstream_failure")

        if any(k in text_l for k in ["performance", "response time", "throughput", "load"]) and "Performance" in selected_test_types:
            if "API" in selected_layers:
                add_if("API", "Positive", "non_functional", "Response time remains within SLA under expected load", "nf_performance_api", functional_type="", non_functional_type="Performance")
        if "Accessibility" in selected_test_types and "UI" in selected_layers:
            if any(k in text_l for k in ["field", "screen", "form", "ui", "page"]):
                add_if("UI", "Positive", "non_functional", "Form remains keyboard accessible with clear labels", "nf_accessibility_ui", functional_type="", non_functional_type="Accessibility")

        if not results:
            preferred = self._layers_allowed(["UI", "API", "Database", "ETL"], selected_layers)
            if preferred:
                add(self._base_blueprint(req, domain_context, "Positive", "business_valid_flow", f"Validate {req['ac_id']}", preferred[0], "Functional", "", "generic_positive"))
                if len(preferred) > 1:
                    add(self._base_blueprint(req, domain_context, "Negative", "validation_or_rejection", f"Reject invalid processing for {req['ac_id']}", preferred[1], "Functional", "", "generic_negative"))
        return results

    def _online_derive(self, requirements: list[dict], domain_context: dict, selected_layers: list[str], selected_test_types: list[str], llm_config: dict, progress_callback=None) -> list[dict]:
        # Use a lower max_tokens for A4 — blueprints are compact (no steps/expected results).
        # Cap at 1500 to stay well within bridge limits; one call per AC keeps payloads small.
        client = LLMClient(
            model=llm_config.get("model", ""),
            api_key=llm_config.get("api_key", ""),
            base_url=llm_config.get("base_url", ""),
            temperature=llm_config.get("temperature", 0.2),
            max_tokens=min(llm_config.get("max_tokens", 1500), 1500),
            use_json_format=llm_config.get("use_json_format", True),
        )
        if not client.is_configured():
            raise ValueError("LLM configuration incomplete for A4 online mode")

        module = domain_context["module_or_submodules"][0] if domain_context["module_or_submodules"] else "General"
        submodule = domain_context["module_or_submodules"][1] if len(domain_context["module_or_submodules"]) > 1 else ""

        system = (
            "You are a senior enterprise QA architect specialising in scenario derivation. "
            "Return strict JSON only — no markdown, no prose, no explanation outside the JSON.\n\n"
            "Expand the given acceptance criterion into scenario blueprints using: equivalence partitioning, "
            "boundary value analysis, state transitions, and domain-specific enrichment.\n\n"
            "RULES:\n"
            "- Mandatory field AC: include valid, blank, whitespace-only, max-length, format-invalid variants.\n"
            "- Uniqueness AC: include unique-value, duplicate-active, self-same-value, duplicate-inactive variants.\n"
            "- Auth AC: include authorized-role, unauthorized-role, unauthenticated, expired-token, cross-ownership variants.\n"
            "- Audit AC: include created, old-and-new-values, partial-field-change, no-record-on-failure, immutability variants.\n"
            "- Downstream/sync AC: include sync-triggered, correct-payload, no-sync-on-failure, failure-resilience, race-condition variants.\n"
            "- Only use layers present in allowed_layers.\n"
            "- Keep each blueprint atomic — one scenario per blueprint, no test steps.\n"
            "- Every blueprint must include: story_id, story_title, ac_id, ac_text, domain, module, submodule, "
            "seed_type (Positive|Negative|Edge Case|Exception Handling), focus, title_hint, "
            "scenario_key (snake_case), layer_candidates (array, one item from allowed_layers), "
            "functional_test_type, non_functional_type, risk_tags.\n"
        )

        all_blueprints: list[dict] = []
        total = len(requirements)
        completed = 0

        for req in requirements:
            story_id = req["story_id"]
            user_msg = json.dumps({
                "story_id": story_id,
                "story_title": req["story_title"],
                "ac_id": req["ac_id"],
                "ac_text": req["text"],
                "domain_context": {
                    "primary_domain": domain_context["primary_domain"],
                    "module": module,
                    "project_state": domain_context.get("project_state", ""),
                },
                "allowed_layers": selected_layers,
                "selected_test_types": selected_test_types,
                "output_instructions": [
                    "Return JSON with a single key 'scenario_blueprints' containing an array.",
                    "Generate all meaningful scenario variants for this single AC.",
                    "Do not truncate — include every distinct variant the AC implies.",
                ],
            }, indent=2)

            try:
                payload = client.generate_json(system, user_msg)
                raw = payload.get("scenario_blueprints", [])
                if not isinstance(raw, list):
                    raw = []
            except Exception:
                # Fallback to offline derivation for this AC on LLM error
                raw = []
                for bp in self._derive_for_requirement(req, domain_context, selected_layers, selected_test_types):
                    all_blueprints.append(bp)
                completed += 1
                if progress_callback:
                    progress_callback(completed, total, f"A4 {completed}/{total}: {req['ac_id']} (offline fallback)")
                continue

            for bp in raw:
                bp.setdefault("story_id", story_id)
                bp.setdefault("story_title", req["story_title"])
                bp.setdefault("ac_id", req["ac_id"])
                bp.setdefault("ac_text", req["text"])
                bp.setdefault("domain", domain_context["primary_domain"])
                bp.setdefault("module", module)
                bp.setdefault("submodule", submodule)
                bp.setdefault("functional_test_type", "Functional")
                bp.setdefault("non_functional_type", "")
                bp.setdefault("risk_tags", [])
                bp.setdefault("focus", "")
                bp.setdefault("title_hint", bp.get("scenario_key", ""))
                bp.setdefault("scenario_key", "generic_positive")
                # seed_type is used by A5 offline; normalise from whatever the LLM returned
                bp.setdefault("seed_type", bp.get("scenario_type") or "Positive")
                candidates = bp.get("layer_candidates", [])
                if not isinstance(candidates, list) or not candidates:
                    candidates = [selected_layers[0]] if selected_layers else ["API"]
                candidates = [c for c in candidates if c in selected_layers] or ([selected_layers[0]] if selected_layers else ["API"])
                bp["layer_candidates"] = candidates[:1]
                all_blueprints.append(bp)

            completed += 1
            if progress_callback:
                progress_callback(completed, total, f"A4 {completed}/{total}: {req['ac_id']}")

        return all_blueprints

    def execute(self, requirements: list[dict], domain_context: dict, selected_layers: list[str], selected_test_types: list[str], execution_mode: str = "offline", llm_config: dict | None = None, progress_callback=None) -> dict:
        if execution_mode == "online" and llm_config:
            raw_blueprints = self._online_derive(requirements, domain_context, selected_layers, selected_test_types, llm_config, progress_callback=progress_callback)
        else:
            raw_blueprints = []
            for req in requirements:
                raw_blueprints.extend(self._derive_for_requirement(req, domain_context, selected_layers, selected_test_types))

        blueprints = []
        counter = 1
        for bp in raw_blueprints:
            bp["scenario_id"] = f"SC{counter:04d}"
            counter += 1
            blueprints.append(bp)
        blueprints.sort(key=lambda x: (x["story_id"], x["ac_id"], x["scenario_id"]))
        return {"scenario_blueprints": blueprints}

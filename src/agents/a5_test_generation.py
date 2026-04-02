from __future__ import annotations
import json
import time
from src.agents.base import AgentBase
from src.llm.client import LLMClient
from src.rag.retriever import RAGRetriever


class A5TestGeneration(AgentBase):
    def __init__(self, base_dir):
        super().__init__(base_dir, "A5 Test Cases Generation - Offline.updated.json")
        self.rag = RAGRetriever()

    def _offline_generate_one(self, bp: dict) -> dict:
        layer = bp["layer_candidates"][0]
        scenario_key = bp.get("scenario_key", "general")
        ac_text = bp["ac_text"]
        domain = bp["domain"]
        module = bp["module"]
        functional_type = bp.get("functional_test_type", "Functional")
        non_functional_type = bp.get("non_functional_type", "")

        preconditions = [f"{module} module is available in a stable test environment."]
        test_data = [f"Domain: {domain}", f"Requirement: {bp['ac_id']}"]
        steps = []
        expected = ""
        title = bp.get("title_hint") or f"Validate {bp['ac_id']}"

        library = {
            "ui_valid_required": {
                "pre": ["User has edit access.", "An existing record is available."],
                "steps": ["Open the editable profile screen.", "Enter valid values for all mandatory fields.", "Save the change."],
                "expected": "Update succeeds and saved values are visible in the UI.",
            },
            "ui_required_blank": {
                "pre": ["User has edit access."],
                "steps": ["Open the editable form.", "Leave one required field blank and keep the others valid.", "Attempt to save."],
                "expected": "Field-specific validation is shown and the update is blocked without saving partial data.",
            },
            "api_missing_required": {
                "pre": ["Authorized API client is available."],
                "steps": ["Prepare an update payload with a missing required field.", "Invoke the update API.", "Inspect status code and validation payload."],
                "expected": "API returns a validation or business-rule error and no data update is committed.",
            },
            "db_no_partial_persist": {
                "pre": ["A rejected update scenario is available."],
                "steps": ["Trigger the invalid update through the appropriate entry point.", "Query the affected record and related audit/history tables.", "Compare persisted values with the pre-update state."],
                "expected": "No partial or unintended persistence is observed after the rejected request.",
            },
            "ui_whitespace_boundary": {
                "pre": ["User has edit access."],
                "steps": ["Open the editable form.", "Enter values with leading and trailing spaces or boundary length values.", "Save the change."],
                "expected": "Whitespace and boundary values are handled per business rule without corrupting saved data.",
            },
            "ui_unique_value": {
                "pre": ["User has edit access.", "A unique candidate value is available."],
                "steps": ["Open the profile screen.", "Enter a unique value for the constrained field.", "Save the change."],
                "expected": "Save succeeds and the profile reflects the updated unique value.",
            },
            "ui_duplicate_active": {
                "pre": ["User has edit access.", "A duplicate value already exists on another active record."],
                "steps": ["Open the profile screen.", "Enter the duplicate active value.", "Attempt to save."],
                "expected": "Validation or business error is shown and the update is blocked.",
            },
            "api_duplicate_active": {
                "pre": ["Authorized API client is available.", "A duplicate active value exists."],
                "steps": ["Prepare an update request using the duplicate active value.", "Invoke the API.", "Validate status code and error body."],
                "expected": "API rejects the duplicate value with a business-rule error and no update is committed.",
            },
            "db_duplicate_not_stored": {
                "pre": ["A duplicate-value scenario is available."],
                "steps": ["Trigger the duplicate update through UI or API.", "Inspect the master record and relevant unique-key or validation tables.", "Confirm stored values remain unchanged."],
                "expected": "The duplicate value is not persisted in customer master data.",
            },
            "ui_inactive_duplicate_rule": {
                "pre": ["The same value exists only on an inactive record."],
                "steps": ["Open the profile screen.", "Enter the value that exists on an inactive record.", "Save and observe rule behavior."],
                "expected": "Behavior follows the active-vs-inactive rule consistently and is clearly communicated to the user.",
            },
            "ui_unauthorized_role": {
                "pre": ["User is logged in without update permission."],
                "steps": ["Open the profile screen.", "Attempt to access edit controls and save a change.", "Observe UI permissions and messages."],
                "expected": "Edit action is hidden, disabled, or denied with a clear authorization message and no update occurs.",
            },
            "api_unauthorized_token": {
                "pre": ["A valid token without required permission is available."],
                "steps": ["Prepare a valid update payload.", "Call the update API with an unauthorized token.", "Inspect status code and error payload."],
                "expected": "API returns 401 or 403 and no data is updated.",
            },
            "api_unauthenticated": {
                "pre": ["No valid session or token is provided."],
                "steps": ["Attempt to call the update API without authentication.", "Inspect the response status and body.", "Verify no side effects occurred."],
                "expected": "Authentication failure is returned and the system remains unchanged.",
            },
            "integration_bypass_denied": {
                "pre": ["A direct backend or integration endpoint is known.", "Caller lacks update permission."],
                "steps": ["Attempt to invoke the backend or integration path directly.", "Observe status, logs, and downstream effects.", "Verify record state and audit behavior."],
                "expected": "Direct bypass is denied and no data or audit change is created.",
            },
            "ui_audit_created": {
                "pre": ["Authorized user exists.", "The current values are known before update."],
                "steps": ["Change one or more fields through the UI.", "Save the record.", "Open audit history or audit-facing UI if available."],
                "expected": "Audit history reflects the change with actor, timestamp, and old/new values.",
            },
            "db_audit_old_new": {
                "pre": ["A successful update has been completed."],
                "steps": ["Query audit and history tables for the updated record.", "Compare the stored old values with the pre-update state.", "Compare the stored new values with the saved state."],
                "expected": "Audit tables store accurate old and new values for the transaction.",
            },
            "db_audit_changed_fields": {
                "pre": ["Only a subset of fields is changed in the update."],
                "steps": ["Execute an update that changes only one relevant field.", "Inspect the audit record.", "Validate field-level change markers."],
                "expected": "Only changed fields are marked as changed and unchanged fields are not falsely logged.",
            },
            "db_no_audit_for_failed": {
                "pre": ["An invalid update scenario is available."],
                "steps": ["Attempt an invalid update that should fail.", "Inspect audit and history storage.", "Validate whether any success audit was created."],
                "expected": "No successful audit change record is created for a failed update attempt.",
            },
            "etl_sync_success": {
                "pre": ["Downstream sync or integration is enabled."],
                "steps": ["Update the source record successfully.", "Trigger or wait for the sync mechanism.", "Inspect integration logs or downstream record state."],
                "expected": "Approved source updates are propagated successfully to the downstream system.",
            },
            "etl_payload_transform": {
                "pre": ["Integration payload or log inspection is possible."],
                "steps": ["Execute a successful update.", "Inspect outbound payload, mapping logs, or transform output.", "Compare transformed fields with the approved source values."],
                "expected": "Outbound payload contains the latest approved values in the expected format and mapping.",
            },
            "etl_downstream_failure": {
                "pre": ["A downstream outage or failure can be simulated."],
                "steps": ["Execute a successful source update.", "Force downstream unavailability during sync.", "Inspect logs, retry flags, or exception queues."],
                "expected": "Failure is logged clearly and the record is marked for retry or exception handling without data loss.",
            },
            "e2e_valid_sync": {
                "pre": ["End-to-end environment is ready."],
                "steps": ["Update the record through the primary business entry point.", "Verify saved state, audit trail, and downstream propagation.", "Confirm the final state in dependent systems."],
                "expected": "The full business journey completes successfully with consistent final state across systems.",
            },
            "e2e_invalid_no_sync": {
                "pre": ["An invalid update scenario is available and downstream sync can be observed."],
                "steps": ["Attempt the invalid update.", "Verify validation failure and source non-persistence.", "Confirm downstream systems remain unchanged."],
                "expected": "Invalid source updates do not persist and do not leak into downstream systems.",
            },
            "nf_performance_api": {
                "pre": ["Performance test environment and expected workload are defined."],
                "steps": ["Run the update API under expected concurrent load.", "Capture latency, error rate, and throughput metrics.", "Compare results with target SLA or acceptance threshold."],
                "expected": "Response time, throughput, and error rate remain within agreed limits under expected load.",
            },
            "nf_accessibility_ui": {
                "pre": ["Keyboard and screen-reader checks can be performed."],
                "steps": ["Navigate the form using keyboard-only interaction.", "Check labels, focus order, and actionable controls.", "Attempt key success and validation paths."],
                "expected": "Core form interactions remain accessible with clear labels, focus behavior, and feedback.",
            },
            "generic_positive": {
                "pre": ["Valid business context exists."],
                "steps": ["Execute the flow using valid data.", "Observe system behavior.", "Verify the outcome."],
                "expected": "The business rule is satisfied successfully.",
            },
            "generic_negative": {
                "pre": ["An invalid or risky input variant is available."],
                "steps": ["Execute the flow using invalid or conflicting data.", "Observe response and persistence behavior.", "Verify errors and rollback or non-persistence."],
                "expected": "Invalid processing is rejected cleanly without unintended side effects.",
            },
        }

        selected = library.get(scenario_key, library["generic_positive"])
        preconditions.extend(selected["pre"])
        steps.extend(selected["steps"])
        expected = selected["expected"]

        if non_functional_type:
            functional_type = ""
        if layer == "UI" and scenario_key.startswith("ui_"):
            test_data.append("Use values relevant to the visible fields and validation messages.")
        elif layer == "API":
            test_data.append("Use request payloads and tokens aligned to the scenario.")
        elif layer == "Database":
            test_data.append("Use record identifiers that allow before/after comparison in persistence or audit storage.")
        elif layer == "ETL Integration":
            test_data.append("Use a record that can be traced through payload, mapping, or downstream status.")
        elif layer == "E2E":
            test_data.append("Use a business record that can be traced across source and downstream systems.")

        return {
            "story_id": bp["story_id"],
            "story_title": bp["story_title"],
            "ac_id": bp["ac_id"],
            "ac_text": bp["ac_text"],
            "title": title,
            "domain": domain,
            "module": module,
            "submodule": bp.get("submodule", ""),
            "test_case_layer": layer,
            "scenario_type": bp["seed_type"],
            "functional_test_type": functional_type,
            "non_functional_type": non_functional_type,
            "preconditions": preconditions,
            "test_data": test_data,
            "steps": steps,
            "expected_result": expected,
            "tags": [domain, layer, bp["seed_type"], bp.get("focus", ""), bp["ac_id"]],
            "risk_tags": list(bp.get("risk_tags", [])),
            "source": "offline_rules",
        }

    def _merge_with_blueprint(self, bp: dict, tc: dict) -> dict:
        merged = self._offline_generate_one(bp)
        merged.update(tc or {})
        for key in ["story_id", "story_title", "ac_id", "ac_text", "domain", "module", "submodule"]:
            merged[key] = bp.get(key, merged.get(key))
        if not merged.get("test_case_layer"):
            merged["test_case_layer"] = bp["layer_candidates"][0]
        merged.setdefault("functional_test_type", bp.get("functional_test_type", "Functional"))
        merged.setdefault("non_functional_type", bp.get("non_functional_type", ""))
        return merged

    def _online_generate_from_groups(self, blueprints: list[dict], drafts: list[dict], document_text: str, llm_config: dict, fail_on_error: bool = True) -> tuple[list[dict], dict]:
        client = LLMClient(
            model=llm_config.get("model", ""),
            api_key=llm_config.get("api_key", ""),
            base_url=llm_config.get("base_url", ""),
            temperature=llm_config.get("temperature", 0.2),
            max_tokens=llm_config.get("max_tokens", 3200),
            use_json_format=llm_config.get("use_json_format", True),
        )
        meta = {"requested": True, "used": False, "fallback_reason": "", "generator_source": "offline_rules", "model": llm_config.get("model", ""), "base_url": llm_config.get("base_url", ""), "batch_count": 0, "response_time_sec": 0.0, "raw_preview": "", "strategy": "grouped_ac_generation"}
        if not client.is_configured():
            meta["fallback_reason"] = "LLM configuration incomplete"
            if fail_on_error:
                raise ValueError(meta["fallback_reason"])
            return drafts, meta

        def group_key(bp: dict):
            return (bp["story_id"], bp["ac_id"])

        groups = {}
        for bp, draft in zip(blueprints, drafts):
            groups.setdefault(group_key(bp), {"blueprints": [], "drafts": []})
            groups[group_key(bp)]["blueprints"].append(bp)
            groups[group_key(bp)]["drafts"].append(draft)

        out = []
        try:
            started = time.time()
            for (story_id, ac_id), payload_group in groups.items():
                group_blueprints = payload_group["blueprints"]
                group_drafts = payload_group["drafts"]
                rag = self.rag.retrieve(document_text, " ".join(f"{b['ac_text']} {b['module']} {b['domain']}" for b in group_blueprints), top_k=4)
                allowed_layers = sorted({bp["layer_candidates"][0] for bp in group_blueprints})
                system = (
                    "You are an expert enterprise QA architect. Return strict JSON only. "
                    "Generate business-specific, execution-ready test cases for ONE acceptance criterion. "
                    "Do not create mechanical clones across layers. Use layers only when justified. "
                    "Prefer UI and API for interactive business flows. Use Database, ETL Integration, and E2E only when the AC truly implies them. "
                    "All array fields must remain JSON arrays."
                )
                user = json.dumps({
                    "story_id": story_id,
                    "ac_id": ac_id,
                    "retrieved_context": rag,
                    "document_excerpt": document_text[:6000],
                    "allowed_layers": allowed_layers,
                    "seed_blueprints": group_blueprints,
                    "draft_examples": group_drafts,
                    "generation_rules": [
                        "Return JSON with key test_cases.",
                        "Generate 2 to 5 strong test cases for this AC depending on need; do not force all layers.",
                        "Every title must be concrete and business-readable, not generic or template-style.",
                        "Each test case must include: title, test_case_layer, scenario_type, functional_test_type, non_functional_type, preconditions, test_data, steps, expected_result.",
                        "UI tests should mention visible controls, validation messages, OTP, document upload, or claim status when relevant.",
                        "API tests should mention payload, auth, response/status code, validation contract, or duplicate prevention when relevant.",
                        "Database tests should mention persistence, duplicate check, calculation result, audit, or before/after validation only when justified.",
                        "ETL Integration tests should mention notifications, downstream events, message delivery, retry, or status propagation only when justified.",
                        "E2E tests should be used sparingly for the most critical business journey only.",
                        "Do not repeat the same scenario intent across multiple layers unless the layer adds unique verification value.",
                        "For insurance claim flows, include realistic test data and domain terminology where relevant."
                    ]
                }, indent=2)
                payload = client.generate_json(system, user)
                meta["batch_count"] += 1
                if not meta["raw_preview"]:
                    meta["raw_preview"] = json.dumps(payload, ensure_ascii=False)[:1200]
                improved = payload.get("test_cases", [])
                if not isinstance(improved, list) or not improved:
                    raise ValueError(f"LLM returned no test cases for {story_id}/{ac_id}")
                for tc in improved:
                    base_bp = group_blueprints[0]
                    merged = self._merge_with_blueprint(base_bp, tc)
                    # Allow LLM to choose a justified layer from allowed layers.
                    chosen_layer = merged.get("test_case_layer") or merged.get("layer") or base_bp["layer_candidates"][0]
                    if chosen_layer not in allowed_layers:
                        chosen_layer = allowed_layers[0]
                    merged["test_case_layer"] = chosen_layer
                    merged["story_id"] = story_id
                    merged["ac_id"] = ac_id
                    merged["story_title"] = base_bp["story_title"]
                    merged["ac_text"] = base_bp["ac_text"]
                    merged["domain"] = base_bp["domain"]
                    merged["module"] = base_bp["module"]
                    merged["submodule"] = base_bp.get("submodule", "")
                    merged["source"] = "online_llm"
                    out.append(merged)
            meta["used"] = True
            meta["generator_source"] = "online_llm"
            meta["response_time_sec"] = round(time.time() - started, 2)
            return out, meta
        except Exception as exc:
            meta["fallback_reason"] = str(exc)
            meta["response_time_sec"] = round(time.time() - started, 2) if "started" in locals() else 0.0
            if fail_on_error:
                raise RuntimeError(str(exc)) from exc
            return drafts, meta

    def execute(self, scenario_blueprints: list[dict], document_text: str, execution_mode: str, llm_config: dict) -> dict:
        drafts = [self._offline_generate_one(bp) for bp in scenario_blueprints]
        llm_meta = {"requested": execution_mode == "online", "used": False, "fallback_reason": "", "generator_source": "offline_rules"}
        tests = drafts
        if execution_mode == "online":
            tests, llm_meta = self._online_generate_from_groups(scenario_blueprints, drafts, document_text, llm_config, fail_on_error=True)
        for idx, tc in enumerate(tests, start=1):
            tc["test_case_id"] = f"TC{idx:05d}"
            if not tc.get("automated"):
                tc["automated"] = "May be"
        return {"test_cases": tests, "llm_meta": llm_meta}

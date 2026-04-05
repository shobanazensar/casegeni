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

        preconditions = [
            f"Application is deployed and accessible in the test environment.",
            f"{module} module is available and the feature under test is enabled.",
        ]
        test_data = [
            f"Domain: {domain}",
            f"Acceptance Criterion: {bp['ac_id']}",
            f"Requirement Text: {ac_text[:120]}",
        ]
        steps = []
        expected = ""
        title = bp.get("title_hint") or f"Validate {bp['ac_id']}"

        library = {
            "ui_valid_required": {
                "pre": [
                    "Application is deployed and accessible in the test environment.",
                    "User account exists with a role that has Edit permission for the module under test.",
                    "An existing record is available with all mandatory fields currently populated.",
                ],
                "steps": [
                    "Log in to the application with the Edit-permitted user account.",
                    "Navigate to the module and open the existing record in edit mode.",
                    "Enter a valid value for each mandatory field as defined in Test Data.",
                    "Click Save.",
                ],
                "expected": "Record is saved successfully. All values entered appear correctly on the record view. No validation error messages are displayed.",
            },
            "ui_required_blank": {
                "pre": [
                    "Application is deployed and accessible in the test environment.",
                    "User account exists with a role that has Edit permission for the module under test.",
                    "An existing record is open in edit mode.",
                ],
                "steps": [
                    "Log in to the application with the Edit-permitted user account.",
                    "Navigate to the module and open the existing record in edit mode.",
                    "Clear the value in one mandatory field while keeping all other fields valid.",
                    "Click Save.",
                ],
                "expected": "An inline validation message is displayed immediately adjacent to the blank mandatory field identifying the field by name. The record is not saved and no data is persisted.",
            },
            "api_missing_required": {
                "pre": [
                    "API endpoint is accessible in the test environment.",
                    "A valid authentication token with the required permission scope is available.",
                    "A baseline request payload with all mandatory fields populated is prepared.",
                ],
                "steps": [
                    "Construct the request payload by removing one mandatory field from the baseline payload.",
                    "Submit a POST or PUT request to the update endpoint with the incomplete payload.",
                    "Capture the HTTP response status code and the full response body.",
                ],
                "expected": "API returns HTTP 400 or 422. Response body contains a field-level error message identifying the missing mandatory field by name. No record is created or updated in the database.",
            },
            "db_no_partial_persist": {
                "pre": [
                    "Database is accessible via query tool in the test environment.",
                    "A target record exists with known current field values recorded before the test.",
                    "A reproducible invalid update scenario that will cause validation failure is identified.",
                ],
                "steps": [
                    "Record the current field values of the target record from the database.",
                    "Trigger the invalid update via UI or API to cause a validation failure.",
                    "Query the target record and related audit or history tables in the database.",
                    "Compare the queried values against the values recorded in step 1.",
                ],
                "expected": "All field values of the target record are identical to the values recorded before the update attempt. No partial update exists and no new audit entry is inserted for the failed operation.",
            },
            "ui_whitespace_boundary": {
                "pre": [
                    "Application is deployed and accessible in the test environment.",
                    "User account exists with a role that has Edit permission for the module under test.",
                    "An existing record is available for editing.",
                    "Field length and whitespace-handling rules are documented in the requirements.",
                ],
                "steps": [
                    "Log in to the application with the Edit-permitted user account.",
                    "Navigate to the module and open the record in edit mode.",
                    "Enter a value with leading and trailing whitespace spaces in the field under test.",
                    "Enter a value at the maximum allowed character length in the same field.",
                    "Click Save after each entry and inspect the stored value.",
                ],
                "expected": "Leading and trailing whitespace is trimmed on save as per the business rule. A value at the maximum allowed length is accepted and stored without truncation or error. Values exceeding the maximum length are rejected with a specific character-limit validation message.",
            },
            "ui_unique_value": {
                "pre": [
                    "Application is deployed and accessible in the test environment.",
                    "User account exists with a role that has Edit permission for the module under test.",
                    "A value that does not exist on any other active record in the system is identified and available as Test Data.",
                ],
                "steps": [
                    "Log in to the application with the Edit-permitted user account.",
                    "Navigate to the module and open the target record in edit mode.",
                    "Enter the unique value from Test Data into the constrained field.",
                    "Click Save.",
                ],
                "expected": "Record is saved successfully. The constrained field displays the new unique value on the record view. No validation or uniqueness error is displayed.",
            },
            "ui_duplicate_active": {
                "pre": [
                    "Application is deployed and accessible in the test environment.",
                    "User account exists with a role that has Edit permission for the module under test.",
                    "A second active record exists in the system that already holds the duplicate value identified in Test Data.",
                ],
                "steps": [
                    "Log in to the application with the Edit-permitted user account.",
                    "Navigate to the module and open the target record in edit mode.",
                    "Enter the duplicate value from Test Data into the constrained field.",
                    "Click Save.",
                ],
                "expected": "Save is blocked. A specific business-rule or uniqueness validation message is displayed identifying the conflict. No change is committed to the record.",
            },
            "api_duplicate_active": {
                "pre": [
                    "API endpoint is accessible in the test environment.",
                    "A valid authentication token with the required permission scope is available.",
                    "A second active record already holds the duplicate value identified in Test Data.",
                ],
                "steps": [
                    "Construct the request payload using the duplicate value from Test Data in the constrained field.",
                    "Submit a POST or PUT request to the update endpoint.",
                    "Capture the HTTP response status code and the full response body.",
                ],
                "expected": "API returns HTTP 400 or 409. Response body contains a uniqueness or business-rule error message. The target record is not updated and no new record is created in the database.",
            },
            "db_duplicate_not_stored": {
                "pre": [
                    "Database is accessible via query tool in the test environment.",
                    "The target record's current constrained field value is recorded before the test.",
                    "A duplicate-value rejection scenario is reproducible via UI or API.",
                ],
                "steps": [
                    "Record the current constrained field value of the target record from the database.",
                    "Trigger the duplicate-value update through UI or API to cause a rejection.",
                    "Query the master record and any unique-key constraint tables in the database.",
                    "Compare the stored constrained field value against the value recorded in step 1.",
                ],
                "expected": "The constrained field value in the database remains identical to the value recorded before the duplicate attempt. No new entry is inserted into unique-key or validation tables for this record.",
            },
            "ui_inactive_duplicate_rule": {
                "pre": [
                    "Application is deployed and accessible in the test environment.",
                    "User account exists with a role that has Edit permission for the module under test.",
                    "An inactive record exists in the system that already holds the value identified in Test Data.",
                    "No active record holds the same value.",
                ],
                "steps": [
                    "Log in to the application with the Edit-permitted user account.",
                    "Navigate to the module and open the target record in edit mode.",
                    "Enter the value that exists on the inactive record into the constrained field.",
                    "Click Save.",
                ],
                "expected": "Outcome is consistent with the documented active-versus-inactive uniqueness rule. If the rule permits reuse against inactive records, the save succeeds and the value is displayed on the record. If the rule blocks reuse regardless of inactive status, a specific validation message is displayed and the record is not saved.",
            },
            "ui_unauthorized_role": {
                "pre": [
                    "Application is deployed and accessible in the test environment.",
                    "User account exists with a role that has read-only or no permission for the module under test (no Edit permission assigned).",
                    "A record exists in the module that would be the target of an edit attempt.",
                ],
                "steps": [
                    "Log in to the application with the read-only or non-permitted user account.",
                    "Navigate to the module and open the target record.",
                    "Attempt to locate and interact with any Edit or Save control on the record view.",
                ],
                "expected": "Edit controls are either hidden or visibly disabled. If an edit action is attempted, the system displays an authorisation-denied message. No change is committed to the record.",
            },
            "api_unauthorized_token": {
                "pre": [
                    "API endpoint is accessible in the test environment.",
                    "A valid authentication token is available that is scoped to a role without the required update permission.",
                    "A valid request payload is prepared.",
                ],
                "steps": [
                    "Construct a valid request payload for the update operation.",
                    "Submit a POST or PUT request to the update endpoint using the under-privileged token in the Authorization header.",
                    "Capture the HTTP response status code and the full response body.",
                ],
                "expected": "API returns HTTP 401 or 403. Response body contains an authorisation error message. No record is created or updated in the database.",
            },
            "api_unauthenticated": {
                "pre": [
                    "API endpoint is accessible in the test environment.",
                    "No valid session token or API key is available for the request.",
                    "A valid request payload is prepared.",
                ],
                "steps": [
                    "Construct a valid request payload for the update operation.",
                    "Submit the request to the update endpoint with the Authorization header omitted entirely.",
                    "Capture the HTTP response status code and the full response body.",
                    "Query the database to confirm no change was committed.",
                ],
                "expected": "API returns HTTP 401. Response body contains an authentication error message. No record is created or updated in the database.",
            },
            "integration_bypass_denied": {
                "pre": [
                    "The backend or integration endpoint URL is known and accessible in the test environment.",
                    "A caller credential or token is available that lacks the required update permission.",
                    "A valid request payload is prepared.",
                ],
                "steps": [
                    "Construct a valid request payload targeting the integration or backend endpoint directly.",
                    "Submit the request using the under-privileged credential.",
                    "Capture the response status code and body.",
                    "Inspect integration logs and query the target record in the database.",
                ],
                "expected": "Direct call to the integration or backend endpoint returns HTTP 401 or 403. No data record is created or updated. No audit entry is created. Integration logs do not contain a success event for this request.",
            },
            "ui_audit_created": {
                "pre": [
                    "Application is deployed and accessible in the test environment.",
                    "User account exists with a role that has Edit permission for the module under test.",
                    "The current field values of the target record are recorded before the test begins.",
                    "Audit history or audit-facing UI is accessible to the test user or tester.",
                ],
                "steps": [
                    "Log in to the application with the Edit-permitted user account.",
                    "Navigate to the module and open the target record in edit mode.",
                    "Change the specified field to the new value defined in Test Data.",
                    "Click Save.",
                    "Navigate to the audit history view for the updated record.",
                ],
                "expected": "An audit history entry is created for the update. The entry records the user account that performed the change, the timestamp of the change, the field name, the old value as recorded before the test, and the new value as entered in step 3.",
            },
            "db_audit_old_new": {
                "pre": [
                    "Database is accessible via query tool in the test environment.",
                    "A successful update has been completed via UI or API and the old and new field values are both known.",
                    "Audit and history tables are identified and accessible for query.",
                ],
                "steps": [
                    "Query the audit or history table for the record updated in the precondition.",
                    "Compare the old_value column in the audit record against the field value that existed before the update.",
                    "Compare the new_value column in the audit record against the field value entered during the update.",
                ],
                "expected": "The audit record exists for the update transaction. The old_value column matches the pre-update field value exactly. The new_value column matches the post-update field value exactly.",
            },
            "db_audit_changed_fields": {
                "pre": [
                    "Database is accessible via query tool in the test environment.",
                    "A record with multiple auditable fields is identified.",
                    "Only one specific field is changed during the update used for this test.",
                ],
                "steps": [
                    "Update only one field of the target record via UI or API.",
                    "Query the audit or history table for the resulting audit entry.",
                    "Inspect field-level change markers or rows for each field in the audit record.",
                ],
                "expected": "The audit record contains a change entry only for the field that was updated. All other fields of the record do not appear as changed in the audit entry.",
            },
            "db_no_audit_for_failed": {
                "pre": [
                    "Database is accessible via query tool in the test environment.",
                    "A reproducible invalid update scenario that will fail validation is identified.",
                    "The total count of audit records for the target record is noted before the test.",
                ],
                "steps": [
                    "Record the current audit record count for the target record in the database.",
                    "Attempt the invalid update via UI or API so that the operation is rejected by the system.",
                    "Query the audit or history table for the target record.",
                    "Compare the audit record count against the count recorded in step 1.",
                ],
                "expected": "The audit record count for the target record after the failed attempt is identical to the count before the attempt. No new audit entry with a success status is inserted for the validation-failed operation.",
            },
            "etl_sync_success": {
                "pre": [
                    "Source system and downstream integration system are deployed and operational in the test environment.",
                    "Downstream sync or integration job is enabled and scheduled or triggerable.",
                    "A target record exists in the source system that is within scope for downstream synchronisation.",
                    "Integration logs and downstream record state are accessible for inspection.",
                ],
                "steps": [
                    "Update the source record with the values defined in Test Data via UI or API.",
                    "Confirm the update is saved successfully in the source system.",
                    "Trigger the sync mechanism or wait for the scheduled integration job to execute.",
                    "Inspect the integration execution log for the processed record.",
                    "Query the corresponding record in the downstream system.",
                ],
                "expected": "Integration log shows a successful processing entry for the updated record with no error status. The corresponding record in the downstream system reflects the exact values updated in the source system.",
            },
            "etl_payload_transform": {
                "pre": [
                    "Source system and downstream integration system are deployed and operational in the test environment.",
                    "Outbound payload inspection or mapping log access is available.",
                    "Field transformation rules or mapping specifications are documented and available for reference.",
                ],
                "steps": [
                    "Update the source record with the values defined in Test Data.",
                    "Trigger the integration job and wait for execution to complete.",
                    "Capture the outbound payload from the integration log or message queue.",
                    "Compare each transformed field in the outbound payload against the expected mapped value per the mapping specification.",
                ],
                "expected": "The outbound payload contains the updated source values mapped and formatted according to the transformation specification. No unmapped, null, or incorrectly formatted fields are present in the payload.",
            },
            "etl_downstream_failure": {
                "pre": [
                    "Source system is deployed and operational in the test environment.",
                    "Downstream system can be made unavailable or a simulated failure can be triggered during the sync window.",
                    "Integration retry queue or exception queue is accessible for inspection.",
                ],
                "steps": [
                    "Update the source record with the values defined in Test Data.",
                    "Simulate downstream unavailability or trigger a downstream failure condition.",
                    "Trigger the integration sync and wait for it to attempt execution.",
                    "Inspect the integration error log and the retry or exception queue.",
                    "Confirm the source record state is unchanged by the failure.",
                ],
                "expected": "The integration log records a failure event for the sync attempt with the downstream error details. The record is placed into the retry queue or exception queue for reprocessing. The source record data is not lost or corrupted. No silent failure or unlogged error occurs.",
            },
            "e2e_valid_sync": {
                "pre": [
                    "End-to-end test environment is deployed with source system, integration layer, and downstream system all operational.",
                    "A business record that can be traced across source and downstream systems exists and is identified in Test Data.",
                    "Audit trail and downstream record state are accessible for verification.",
                ],
                "steps": [
                    "Execute the business update through the primary entry point as defined in Test Data.",
                    "Confirm the update is saved in the source system.",
                    "Trigger or wait for the integration sync to execute.",
                    "Verify the audit trail entry in the source system reflects the correct actor, timestamp, old value, and new value.",
                    "Query the corresponding record in the downstream system.",
                ],
                "expected": "The source system record shows the updated values. The audit trail entry contains the correct actor, timestamp, and old and new field values. The downstream system record reflects the same updated values. No error, mismatch, or missing record is present across any of the three systems.",
            },
            "e2e_invalid_no_sync": {
                "pre": [
                    "End-to-end test environment is deployed with source system, integration layer, and downstream system all operational.",
                    "A reproducible invalid update scenario that will fail validation in the source system is identified.",
                    "The downstream record state before the test is recorded for comparison.",
                ],
                "steps": [
                    "Attempt the invalid update through the primary entry point using the invalid values defined in Test Data.",
                    "Confirm the source system rejects the update and displays a validation message.",
                    "Trigger or wait for the integration sync window to pass.",
                    "Query the source record to confirm no change was persisted.",
                    "Query the downstream record to confirm its state is unchanged.",
                ],
                "expected": "The source system rejects the invalid update with a specific validation message. The source record values are unchanged. The downstream record remains in the same state as recorded before the test. No sync event or record update is present in the integration log for this invalid attempt.",
            },
            "nf_performance_api": {
                "pre": [
                    "Performance test environment is provisioned with infrastructure matching the production specification.",
                    "Target SLA or acceptance threshold values for response time, throughput, and error rate are documented and available.",
                    "Performance test tool is configured with the expected concurrent user load as defined in Test Data.",
                ],
                "steps": [
                    "Configure the performance test tool with the concurrent load level defined in Test Data.",
                    "Execute the update API endpoint under the defined concurrent load for the defined duration.",
                    "Capture average response time, 95th percentile response time, requests per second throughput, and error rate metrics.",
                    "Compare each captured metric against the documented SLA threshold.",
                ],
                "expected": "Average response time is at or below the SLA maximum. 95th percentile response time is at or below the SLA maximum. Throughput meets or exceeds the minimum requests-per-second target. Error rate is at or below the maximum permitted threshold. All metrics are within agreed limits under the defined load.",
            },
            "nf_accessibility_ui": {
                "pre": [
                    "Application is deployed and accessible in the test environment.",
                    "Test is performed using keyboard-only navigation with no mouse interaction.",
                    "Screen-reader software is installed and active if screen-reader verification is in scope.",
                ],
                "steps": [
                    "Navigate to the form or page under test using the Tab key only.",
                    "Verify that each interactive field receives visible keyboard focus in a logical left-to-right and top-to-bottom order.",
                    "Verify that each field has a visible label or accessible name announced by the screen reader.",
                    "Complete the form using keyboard input only and submit.",
                    "Trigger a validation error and verify the error message is announced by the screen reader.",
                ],
                "expected": "All interactive fields receive visible keyboard focus in a logical order. Every field has a visible and descriptive label. Form submission completes successfully via keyboard only. Validation error messages are programmatically associated with their fields and announced by the screen reader.",
            },
            "generic_positive": {
                "pre": [
                    "Application is deployed and accessible in the test environment.",
                    "User account exists with the required role and permissions for the feature under test.",
                    "All reference data or configuration required for the feature is present in the test environment.",
                ],
                "steps": [
                    "Log in to the application with the permitted user account.",
                    "Navigate to the feature under test.",
                    "Execute the business action using the valid values defined in Test Data.",
                    "Observe and record the system outcome.",
                ],
                "expected": "The system accepts the input, completes the business action without errors, and displays a confirmation or updated state that reflects the submitted values.",
            },
            "generic_negative": {
                "pre": [
                    "Application is deployed and accessible in the test environment.",
                    "User account exists with the required role and permissions for the feature under test.",
                    "An invalid or boundary-violating input variant is identified and defined in Test Data.",
                ],
                "steps": [
                    "Log in to the application with the permitted user account.",
                    "Navigate to the feature under test.",
                    "Execute the business action using the invalid values defined in Test Data.",
                    "Observe and record the system response.",
                    "Verify the persistence state has not changed.",
                ],
                "expected": "The system rejects the invalid input with a specific error or validation message identifying the reason. No data is persisted or modified as a result of the rejected action.",
            },
        }

        selected = library.get(scenario_key, library["generic_positive"])
        preconditions.extend(selected["pre"])
        steps.extend(selected["steps"])
        expected = selected["expected"]

        if non_functional_type:
            functional_type = ""
        if layer == "UI" and scenario_key.startswith("ui_"):
            test_data.append(f"User Role: [specify role with exact permissions required, e.g. {module}_Admin or {module}_Editor]")
            test_data.append("Target Record ID: [specify unique identifier of the record under test]")
            test_data.append("Field Under Test: [specify field name and the exact input value to use]")
            test_data.append("Environment: UAT or System Integration Test")
        elif layer == "API":
            test_data.append("Endpoint: [specify full URL and HTTP method, e.g. PUT /api/v1/records/{id}]")
            test_data.append("Auth Token: [specify token type and permission scope, e.g. Bearer token with UPDATE_RECORD scope]")
            test_data.append("Request Payload: [specify the JSON payload including the field under test with its exact value]")
            test_data.append("Expected HTTP Status: [specify exact expected status code, e.g. 200, 400, 401, 422]")
        elif layer == "Database":
            test_data.append("Target Table: [specify table name, e.g. customer_master or audit_log]")
            test_data.append("Record Identifier: [specify primary key or unique identifier for the target row]")
            test_data.append("Pre-Update Field Value: [specify the exact field value before the operation]")
            test_data.append("Post-Update Expected Value: [specify the exact field value expected after the operation]")
        elif layer == "ETL Integration":
            test_data.append("Source Record ID: [specify identifier of the source record under test]")
            test_data.append("Field Under Test: [specify source field name and the value used for this test]")
            test_data.append("Expected Downstream Field: [specify the downstream field name and its expected mapped value]")
            test_data.append("Integration Job Name or Queue: [specify the job or topic name]")
        elif layer == "E2E":
            test_data.append("Business Record ID: [specify the identifier traceable across source and downstream systems]")
            test_data.append("Source System Entry Point: [specify UI screen or API endpoint used to trigger the business action]")
            test_data.append("Downstream System and Field: [specify system name and field expected to reflect the change]")

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

    def _online_generate_from_groups(self, blueprints: list[dict], drafts: list[dict], document_text: str, llm_config: dict, fail_on_error: bool = True, progress_callback=None) -> tuple[list[dict], dict]:
        client = LLMClient(
            model=llm_config.get("model", ""),
            api_key=llm_config.get("api_key", ""),
            base_url=llm_config.get("base_url", ""),
            temperature=llm_config.get("temperature", 0.2),
            max_tokens=llm_config.get("max_tokens", 3200),
            use_json_format=llm_config.get("use_json_format", True),
        )
        meta = {"requested": True, "used": False, "fallback_reason": "", "generator_source": "offline_rules", "model": llm_config.get("model", ""), "base_url": llm_config.get("base_url", ""), "batch_count": 0, "response_time_sec": 0.0, "raw_preview": "", "strategy": "story_batched_generation"}
        if not client.is_configured():
            meta["fallback_reason"] = "LLM configuration incomplete"
            if fail_on_error:
                raise ValueError(meta["fallback_reason"])
            return drafts, meta

        # --- Group by story (one LLM call per story, not per AC) ---
        story_groups: dict[str, dict] = {}
        for bp, draft in zip(blueprints, drafts):
            sid = bp["story_id"]
            if sid not in story_groups:
                story_groups[sid] = {"story_title": bp["story_title"], "acs": {}}
            ac_id = bp["ac_id"]
            if ac_id not in story_groups[sid]["acs"]:
                story_groups[sid]["acs"][ac_id] = {"blueprints": [], "drafts": []}
            story_groups[sid]["acs"][ac_id]["blueprints"].append(bp)
            story_groups[sid]["acs"][ac_id]["drafts"].append(draft)

        # Compact document excerpt (1000 chars is enough context; full text already in blueprint ac_text)
        doc_excerpt = document_text[:1000].strip()

        out: list[dict] = []
        total_stories = len(story_groups)
        completed = 0

        try:
            started = time.time()
            for story_id, story_data in story_groups.items():
                acs_payload = []
                bp_lookup: dict[str, dict] = {}  # ac_id -> first blueprint
                for ac_id, ac_data in story_data["acs"].items():
                    grp_bps = ac_data["blueprints"]
                    allowed_layers = sorted({bp["layer_candidates"][0] for bp in grp_bps})
                    acs_payload.append({
                        "ac_id": ac_id,
                        "ac_text": grp_bps[0]["ac_text"],
                        "allowed_layers": allowed_layers,
                        "seed_blueprints": grp_bps,
                    })
                    bp_lookup[ac_id] = grp_bps[0]

                system = (
                    "You are a senior enterprise QA architect. Return strict JSON only — no markdown, no prose, no explanation outside the JSON. "
                    "Generate business-specific, execution-ready test cases for a user story. "

                    "GOLDEN PRINCIPLES — every test case MUST follow all of these:\n"

                    "PRECONDITIONS — state only, never actions:\n"
                    "  - Must describe system state, user role with exact permissions, configuration, and required data existence BEFORE execution.\n"
                    "  - NEVER write actions as preconditions. BAD: 'Navigate to application'. GOOD: 'Application is deployed and accessible in UAT environment.'\n"
                    "  - NEVER write vague preconditions. BAD: 'User is logged in'. GOOD: 'User account exists with role Payroll_Admin and has active session.'\n"
                    "  - NEVER write assertions as preconditions. BAD: 'Salary is calculated'. GOOD: 'Payroll period for March 2026 is open.'\n"

                    "TEST DATA — specific values, never placeholders:\n"
                    "  - Must contain actual input values, boundary values, reference data, and identifiers that drive the test behaviour.\n"
                    "  - NEVER use vague placeholders. BAD: 'valid salary', 'existing employee', 'any payroll month'.\n"
                    "  - GOOD: 'Employee ID: EMP_10045', 'Basic Salary: 50000', 'Tax Slab: 20%', 'Payroll Month: March 2026'.\n"

                    "STEPS — actions only, one action per step, no assertions mixed in:\n"
                    "  - Each step must begin with a verb and describe exactly one action.\n"
                    "  - NEVER mix assertions into steps. BAD: 'Verify that salary is calculated'. That belongs in Expected Results.\n"
                    "  - NEVER write vague steps. BAD: 'Ensure page loads'. GOOD: 'Click the Calculate Salary button.'\n"
                    "  - Steps must be deterministic — no conditional language like 'if applicable'.\n"

                    "EXPECTED RESULTS — measurable and assertive:\n"
                    "  - Must describe exactly what correctness looks like: system response, data values, state changes, messages, status codes.\n"
                    "  - NEVER use vague language. BAD: 'System works as expected', 'No issues observed', 'Salary should be correct'.\n"
                    "  - GOOD: 'Net salary calculated is 40000. Tax amount is 10000. Payroll status is updated to Calculated.'\n"
                    "  - Use present tense assertive language. BAD: 'System will display'. GOOD: 'System displays'.\n"
                    "  - Each expected result must be independently verifiable and programmatically assertable.\n"

                    "Do not create mechanical layer clones. Use each layer only when it adds unique verification value. "
                    "All array fields must remain JSON arrays."
                )
                user = json.dumps({
                    "story_id": story_id,
                    "story_title": story_data["story_title"],
                    "document_excerpt": doc_excerpt,
                    "acceptance_criteria": acs_payload,
                    "generation_rules": [
                        "Return JSON with a single key 'test_cases' containing an array.",
                        "Each test case must have 'ac_id' matching one of the provided acceptance_criteria ac_id values.",
                        "Generate 2-4 test cases per AC. Do not force all layers — use each layer only when it adds unique verification value.",
                        "Titles must be concrete, business-readable, and describe the specific outcome being verified. BAD: 'Validate AC-01'. GOOD: 'Mandatory field blank returns inline validation error'.",
                        "Each test case must include: ac_id, title, test_case_layer, scenario_type, functional_test_type, non_functional_type, preconditions (array), test_data (array), steps (array), expected_result (string).",
                        "PRECONDITIONS rule: Write system state, user roles with specific permissions, configurations, and required data. Never write actions or assertions as preconditions. Never use vague phrases like 'user is logged in' or 'all configurations are correct'.",
                        "TEST DATA rule: Provide specific, concrete values. Include record identifiers, field names with exact values, permission scopes, HTTP endpoints, or boundary values. Never use placeholders like 'valid data', 'existing record', 'any value'.",
                        "STEPS rule: One action per step. Every step starts with a verb. Never mix assertions into steps — validations go only in expected_result. Never write conditional steps ('if applicable').",
                        "EXPECTED RESULTS rule: Use assertive present-tense language. State exact values, status codes, messages, state changes. Never use vague language like 'system works as expected', 'no issues observed', or 'should be correct'.",
                        "UI tests: reference visible field names, button labels, and specific validation message text.",
                        "API tests: specify HTTP method, endpoint path, expected status code, and response body content.",
                        "Database tests: only when the AC explicitly implies persistence, audit, or data-integrity verification. Reference table names and field values.",
                        "Do not repeat the same scenario intent across layers unless each layer provides a distinct and unique verification not covered by another layer.",
                    ]
                }, indent=2)

                payload = client.generate_json(system, user)
                meta["batch_count"] += 1
                if not meta["raw_preview"]:
                    meta["raw_preview"] = json.dumps(payload, ensure_ascii=False)[:1200]

                improved = payload.get("test_cases", [])
                if not isinstance(improved, list) or not improved:
                    raise ValueError(f"LLM returned no test cases for story {story_id}")

                for tc in improved:
                    ac_id = tc.get("ac_id") or (acs_payload[0]["ac_id"] if acs_payload else "")
                    base_bp = bp_lookup.get(ac_id) or list(bp_lookup.values())[0]
                    allowed_layers = sorted({bp["layer_candidates"][0] for bp in story_groups[story_id]["acs"].get(ac_id, {"blueprints": [base_bp]})["blueprints"]})
                    merged = self._merge_with_blueprint(base_bp, tc)
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

                completed += 1
                if progress_callback:
                    progress_callback(completed, total_stories, f"Story {completed}/{total_stories}: {story_data['story_title'][:50]}")

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

    def execute(self, scenario_blueprints: list[dict], document_text: str, execution_mode: str, llm_config: dict, progress_callback=None) -> dict:
        drafts = [self._offline_generate_one(bp) for bp in scenario_blueprints]
        llm_meta = {"requested": execution_mode == "online", "used": False, "fallback_reason": "", "generator_source": "offline_rules"}
        tests = drafts
        if execution_mode == "online":
            tests, llm_meta = self._online_generate_from_groups(scenario_blueprints, drafts, document_text, llm_config, fail_on_error=True, progress_callback=progress_callback)
        for idx, tc in enumerate(tests, start=1):
            tc["test_case_id"] = f"TC{idx:05d}"
            if not tc.get("automated"):
                tc["automated"] = "May be"
        return {"test_cases": tests, "llm_meta": llm_meta}

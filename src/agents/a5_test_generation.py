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

    @staticmethod
    def _extract_ac_context(bp: dict) -> dict:
        """Derive field name, boundary value, format and role hints from AC text.
        Used to populate test data with meaningful values instead of [specify...] placeholders."""
        import re
        text = bp.get("ac_text", "") or ""
        module = (bp.get("module") or "record").title()
        domain = (bp.get("domain") or "").title()
        seed_type = bp.get("seed_type") or bp.get("scenario_type") or "Positive"

        # ── Field name: first noun phrase before a modal verb ──────────────────
        _NOISE = {"the system", "the application", "a user", "the user", "users",
                  "it", "they", "this", "that", "each", "every", "all", "any", "system"}
        field_name = module
        for pattern in [
            r'(?:^|[.;]\s*)(?:[Tt]he\s+)?([A-Za-z][A-Za-z /\-]{2,50}?)\s+(?:must|should|cannot|shall|needs? to|is required|will be)',
            r'(?:ensure|verify|validate|check)\s+(?:that\s+)?(?:the\s+)?([A-Za-z][A-Za-z /\-]{2,40}?)\s+',
            r'(?:^|\s)(?:[Tt]he\s+)([A-Za-z][A-Za-z /\-]{3,40}?)\s+(?:field|value|attribute|property)\b',
        ]:
            m = re.search(pattern, text)
            if m:
                candidate = m.group(1).strip().rstrip("'s").strip()
                if candidate.lower() not in _NOISE and 2 < len(candidate) < 55:
                    field_name = candidate.title()
                    break

        # ── Boundary / numeric constraint ──────────────────────────────────
        boundary_value = ""
        bm = re.search(
            r'\b(\d[\d,]*\s*(?:character|char|digit|byte|day|second|minute|hour|record|item|user|%|percent)?s?)\b',
            text, re.IGNORECASE
        )
        if bm:
            boundary_value = bm.group(1).strip()

        # ── Format hint ────────────────────────────────────────────────
        format_hint = ""
        fmt_m = re.search(r'(?:format|pattern|regex|valid format)[:\s]+([^\.,;]{4,60})', text, re.IGNORECASE)
        if fmt_m:
            format_hint = fmt_m.group(1).strip()

        # ── Role hint ───────────────────────────────────────────────────
        role_hint = f"{module}_Admin or {module}_Editor"
        rm = re.search(r'\b(admin(?:istrator)?|manager|user|editor|viewer|owner|approver|reviewer)\b', text, re.IGNORECASE)
        if rm:
            role_hint = f"{rm.group(1).title()} role with access to {module}"

        # ── Expected HTTP status by scenario type ─────────────────────────────
        http_status = "200 or 201" if seed_type == "Positive" else ("401 or 403" if "auth" in (bp.get("focus", "") + text).lower() else "400 or 422")

        return {
            "field_name": field_name,
            "boundary_value": boundary_value,
            "format_hint": format_hint,
            "role_hint": role_hint,
            "module": module,
            "domain": domain,
            "http_status": http_status,
            "ac_summary": (text[:150].rstrip() + "...") if len(text) > 150 else text,
        }

    def _offline_generate_one(self, bp: dict) -> dict:
        candidates = bp.get("layer_candidates") or ["UI"]
        layer = candidates[0] if candidates else "UI"
        scenario_key = bp.get("scenario_key", "general")
        ac_text = bp["ac_text"]
        domain = bp["domain"]
        module = bp["module"]
        functional_type = bp.get("functional_test_type", "Functional")
        non_functional_type = bp.get("non_functional_type", "")
        # seed_type set by A4 offline; LLM blueprints may use scenario_type instead
        seed_type = bp.get("seed_type") or bp.get("scenario_type") or "Positive"

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
            "nf_security_api_generic": {
                "pre": [
                    "API endpoint is accessible in the test environment.",
                    "An authentication token with insufficient scope or no token is prepared for the test.",
                    "A valid request payload for the operation under test is prepared.",
                ],
                "steps": [
                    "Prepare a request to the target API endpoint using an invalid, expired, or missing authentication token.",
                    "Submit the request and capture the HTTP response status code and full response body.",
                    "Repeat using a token scoped to a role that does not have permission for the operation.",
                ],
                "expected": "The API returns HTTP 401 for unauthenticated requests and HTTP 403 for unauthorised roles. The response body contains an appropriate error message. No data is created, read, updated, or deleted as a result.",
            },
            "nf_performance_api_generic": {
                "pre": [
                    "API endpoint is accessible in the performance/load test environment.",
                    "A valid authenticated request payload is prepared.",
                    "SLA threshold for response time is documented (e.g. p95 < 500 ms under 50 concurrent users).",
                ],
                "steps": [
                    "Configure a load test with the agreed concurrent-user count and ramp-up period.",
                    "Execute the load test against the target API endpoint using valid authenticated requests.",
                    "Capture p50, p95, and p99 response times and the error rate throughout the test duration.",
                    "Compare the captured metrics against the documented SLA thresholds.",
                ],
                "expected": "p95 response time is at or below the SLA threshold throughout the test. Error rate remains below the accepted threshold. No memory leaks, thread exhaustion, or degraded throughput patterns are observed.",
            },
            "nf_accessibility_ui_generic": {
                "pre": [
                    "Application is deployed and accessible in the test environment.",
                    "A screen-reader tool (e.g. NVDA, VoiceOver) and keyboard-only navigation capability are available.",
                    "The feature under test is enabled and navigable.",
                ],
                "steps": [
                    "Navigate to the feature using keyboard only (Tab, Shift+Tab, Enter, Space, arrow keys) and verify all interactive controls receive visible focus.",
                    "Activate a screen reader and navigate through the page; verify every field, button, and error message has a meaningful label or aria-label.",
                    "Trigger any inline validation and confirm the error message is programmatically associated with its field and announced by the screen reader.",
                    "Verify colour contrast of all foreground text against its background meets the WCAG 2.1 AA ratio of at least 4.5:1.",
                ],
                "expected": "All interactive elements are keyboard reachable and operable. Screen reader announces labels, states, and errors correctly. Colour contrast passes WCAG 2.1 AA. The entire workflow can be completed without a pointer device.",
            },
            "nf_compatibility_ui_generic": {
                "pre": [
                    "Application is deployed and accessible in the test environment.",
                    "Browser and device matrix is defined (e.g. Chrome latest, Firefox latest, Safari latest, Edge latest; desktop and mobile viewport).",
                    "The feature under test is enabled.",
                ],
                "steps": [
                    "Open the feature in each browser defined in the matrix and verify the page renders without layout breaks or missing elements.",
                    "Perform the primary business action (create, edit, or submit) in each browser and verify the outcome is consistent.",
                    "Resize the browser to mobile viewport (320 px wide) and verify the layout is responsive with no horizontal scrollbar.",
                    "Verify that JavaScript errors or console warnings specific to the feature are absent in each browser.",
                ],
                "expected": "The feature renders correctly and all business actions complete successfully across all defined browsers and viewports. No browser-specific regressions, layout breaks, or unhandled JavaScript errors are present.",
            },
            "ui_happy_path_positive": {
                "pre": [
                    "Application is deployed and accessible in the test environment.",
                    "User account exists with the required role and Edit permissions for the module under test.",
                    "All mandatory reference data and configuration are present in the test environment.",
                ],
                "steps": [
                    "Log in to the application with the permitted user account.",
                    "Navigate to the module and open or create the record under test.",
                    "Enter all required fields with valid data as defined in Test Data.",
                    "Submit or save the record.",
                    "Verify the outcome reflects the submitted values.",
                ],
                "expected": "The record is saved successfully. All entered values are displayed correctly on the confirmation or record-view screen. No error or validation messages are shown.",
            },
            "ui_happy_path_alt_positive": {
                "pre": [
                    "Application is deployed and accessible in the test environment.",
                    "User account exists with the required role and Edit permissions for the module under test.",
                    "An alternative set of valid input values is prepared that satisfies all business rules.",
                ],
                "steps": [
                    "Log in to the application with the permitted user account.",
                    "Navigate to the module and open or create the record under test.",
                    "Enter the alternative valid values from Test Data.",
                    "Submit or save the record.",
                    "Verify the outcome reflects the alternative submitted values.",
                ],
                "expected": "The record is saved successfully with the alternative valid values. The system behaviour matches the primary happy-path outcome. No errors are produced.",
            },
            "api_happy_path_positive": {
                "pre": [
                    "API endpoint is accessible in the test environment.",
                    "A valid authentication token with the required permission scope is available.",
                    "A complete and valid request payload is prepared.",
                ],
                "steps": [
                    "Construct the request with a valid payload as defined in Test Data.",
                    "Submit the request to the API endpoint using the correct HTTP method.",
                    "Capture the HTTP response status code and response body.",
                    "Query the database or call the GET endpoint to verify the persisted state.",
                ],
                "expected": "API returns HTTP 200 or 201. Response body confirms the operation completed successfully. The database reflects the expected state change consistent with the submitted values.",
            },
            "api_happy_path_alt_positive": {
                "pre": [
                    "API endpoint is accessible in the test environment.",
                    "A valid authentication token with the required permission scope is available.",
                    "An alternative valid request payload is prepared with different but valid field values.",
                ],
                "steps": [
                    "Construct the request with the alternative valid payload from Test Data.",
                    "Submit the request to the API endpoint using the correct HTTP method.",
                    "Capture the HTTP response status code and response body.",
                ],
                "expected": "API returns HTTP 200 or 201. The alternative valid input is accepted and the response matches the expected outcome for that variant.",
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
            "generic_edge_case": {
                "pre": [
                    "Application is deployed and accessible in the test environment.",
                    "User account exists with the required role and permissions for the feature under test.",
                    "A boundary or edge-condition input value is identified and defined in Test Data.",
                ],
                "steps": [
                    "Log in to the application with the permitted user account.",
                    "Navigate to the feature under test.",
                    "Enter or submit the boundary/edge-condition value defined in Test Data.",
                    "Observe and record the system response.",
                ],
                "expected": "The system handles the boundary input consistently with the documented business rule — either accepting it and processing correctly, or rejecting it with a specific, descriptive validation message.",
            },
        }

        if scenario_key in library:
            selected = library[scenario_key]
        elif seed_type in {"Negative", "Exception Handling"}:
            selected = library["generic_negative"]
        elif seed_type == "Edge Case":
            selected = library["generic_edge_case"]
        else:
            selected = library["generic_positive"]
        preconditions.extend(selected["pre"])
        steps.extend(selected["steps"])
        expected = selected["expected"]

        # ── Derive context from the AC text for all test data entries ────────────
        ctx = self._extract_ac_context(bp)
        is_baseline = scenario_key not in library  # True for A4-generated baseline blueprints

        # For baseline blueprints: sharpen the title and expected result with AC context
        if is_baseline:
            title = f"{layer} | {seed_type} \u2014 {ctx['field_name']} | {bp['ac_id']}"
            boundary_clause = f" Boundary value: {ctx['boundary_value']}." if ctx["boundary_value"] else ""
            expected = expected.rstrip(".") + f".{boundary_clause} Per AC: \"{ctx['ac_summary'][:120]}\""

        if non_functional_type:
            functional_type = ""

        # ── Context-aware test data (no more [specify ...] placeholders) ────────
        boundary_note = f" (boundary: {ctx['boundary_value']})" if ctx["boundary_value"] and seed_type in {"Edge Case", "Negative", "Exception Handling"} else ""
        format_note = f" (format: {ctx['format_hint']})" if ctx["format_hint"] else ""
        if layer == "UI":
            test_data.append(f"User Role: {ctx['role_hint']}")
            test_data.append(f"Target Record ID: Existing {ctx['module']} record in test environment")
            test_data.append(f"Field Under Test: {ctx['field_name']}{boundary_note}{format_note}")
            test_data.append("Environment: UAT or System Integration Test")
        elif layer == "API":
            test_data.append(f"Endpoint: PUT or POST /api/v1/{ctx['module'].lower().replace(' ', '-')}/{{id}}")
            test_data.append(f"Auth Token: Bearer token with {ctx['module'].replace(' ', '')}_UPDATE scope")
            payload_note = f"\"{ctx['field_name']}\": \"<{seed_type.lower()} value{boundary_note}>\""
            test_data.append(f"Request Payload: JSON body with {payload_note}")
            test_data.append(f"Expected HTTP Status: {ctx['http_status']}")
        elif layer == "Database":
            table_name = ctx['module'].lower().replace(' ', '_') + "_master"
            test_data.append(f"Target Table: {table_name} (or related audit/history table)")
            test_data.append(f"Record Identifier: Primary key of {ctx['module']} record under test")
            test_data.append(f"Pre-Update {ctx['field_name']} Value: [value before operation is triggered]")
            test_data.append(f"Post-Update {ctx['field_name']} Expected: [value per AC \u2014 {ctx['ac_summary'][:80]}]")
        elif layer in {"ETL", "ETL Integration"}:
            test_data.append(f"Source Record ID: {ctx['module']} identifier in source system")
            test_data.append(f"Field Under Test: {ctx['field_name']}{boundary_note} in source payload")
            test_data.append(f"Expected Downstream {ctx['field_name']}: mapped value in downstream system per business rule")
            test_data.append(f"Integration Job / Queue: [{ctx['domain']} sync or ETL pipeline name]")
        elif layer in {"E2E", "EndToEnd"}:
            test_data.append(f"Business Record ID: {ctx['module']} identifier traceable across source and downstream systems")
            test_data.append(f"Source Entry Point: UI screen or API endpoint that triggers the {ctx['field_name'].lower()} change")
            test_data.append(f"Downstream System and Field: [system name] — {ctx['field_name']}{boundary_note}")

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
            "scenario_type": seed_type,
            "functional_test_type": functional_type,
            "non_functional_type": non_functional_type,
            "preconditions": preconditions,
            "test_data": test_data,
            "steps": steps,
            "expected_result": expected,
            "tags": [domain, layer, seed_type, bp.get("focus", ""), bp["ac_id"]],
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

    def _online_generate_from_groups(self, blueprints: list[dict], document_text: str, llm_config: dict, fail_on_error: bool = True, progress_callback=None) -> tuple[list[dict], dict]:
        # Cap max_tokens at 2000 per AC call — allows 7-8 test cases per AC comfortably.
        # Per-AC batching keeps input small so total prompt+response stays within bridge limits.
        # Offline drafts are generated LAZILY — only on LLM failure for a specific AC.
        client = LLMClient(
            model=llm_config.get("model", ""),
            api_key=llm_config.get("api_key", ""),
            base_url=llm_config.get("base_url", ""),
            temperature=llm_config.get("temperature", 0.2),
            max_tokens=min(llm_config.get("max_tokens", 2000), 2000),
            use_json_format=llm_config.get("use_json_format", True),
        )
        meta = {"requested": True, "used": False, "fallback_reason": "", "generator_source": "offline_rules", "model": llm_config.get("model", ""), "base_url": llm_config.get("base_url", ""), "batch_count": 0, "response_time_sec": 0.0, "raw_preview": "", "strategy": "per_ac_generation"}
        if not client.is_configured():
            meta["fallback_reason"] = "LLM configuration incomplete"
            if fail_on_error:
                raise ValueError(meta["fallback_reason"])
            return [self._offline_generate_one(bp) for bp in blueprints], meta

        # --- Group blueprints by (story_id, ac_id) — no pre-built drafts ---
        ac_groups: dict[tuple[str, str], dict] = {}
        for bp in blueprints:
            key = (bp["story_id"], bp["ac_id"])
            if key not in ac_groups:
                ac_groups[key] = {
                    "story_id": bp["story_id"],
                    "story_title": bp["story_title"],
                    "ac_id": bp["ac_id"],
                    "ac_text": bp["ac_text"],
                    "blueprints": [],
                }
            ac_groups[key]["blueprints"].append(bp)

        doc_excerpt = document_text[:600].strip()

        system = (
            "You are a senior enterprise QA architect. Return strict JSON only — no markdown, no prose, no explanation outside the JSON. "
            "Generate business-specific, execution-ready test cases for one acceptance criterion.\n\n"
            "MANDATORY COVERAGE RULE — for EVERY AC without exception:\n"
            "  - Always include at least one Positive (scenario_type: Positive) test case — the success/happy-path scenario that proves the AC works end-to-end.\n"
            "  - Never skip the positive case even when the AC is primarily about validation or rejection.\n\n"
            "TEST SUITE CLASSIFICATION (MANDATORY — assign exactly ONE per test case):\n"
            "  - Smoke: system health verification ONLY — app launches, login works, core API responds. No business rule validation.\n"
            "  - Functional: validates a single feature, rule, or acceptance criterion. This is the DEFAULT for all business logic tests.\n"
            "  - EndToEnd: validates a COMPLETE business flow crossing multiple systems/modules (e.g. Hire→Payroll→Payslip). Do NOT use for single-module tests.\n"
            "  NEVER use Regression, Sanity, or any other value as test_suite. Regression belongs in execution_tags only.\n\n"
            "EXECUTION TAGS (optional array — can be empty or contain one or more):\n"
            "  Allowed values: Regression, UAT, Parity, Migration.\n"
            "  Apply Regression when the test should re-run after code changes or fixes.\n\n"
            "CLASSIFICATION RATIONALE: one sentence explaining why the test_suite was chosen.\n\n"
            "NON-FUNCTIONAL TESTS: generate non-functional tests (Performance, Security, etc.) AFTER all functional tests for the AC.\n\n"
            "GOLDEN PRINCIPLES — every test case MUST follow all of these:\n"
            "PRECONDITIONS — state only, never actions:\n"
            "  - Describe system state, user role with exact permissions, config, and required data BEFORE execution.\n"
            "  - NEVER write actions. BAD: 'Navigate to application'. GOOD: 'Application is deployed and accessible in UAT environment.'\n"
            "  - NEVER be vague. BAD: 'User is logged in'. GOOD: 'User account exists with role Customer_Service_Agent and has edit permission on Customer Profile module.'\n"
            "TEST DATA — specific values, never placeholders:\n"
            "  - GOOD: 'Customer ID: CUST-10045', 'Name: John Smith', 'Phone: +1-555-0100'.\n"
            "  - NEVER: 'valid name', 'existing customer', 'any phone number'.\n"
            "STEPS — one action per step, verb-first, no assertions:\n"
            "  - BAD: 'Verify salary is calculated'. GOOD: 'Click the Save button.'\n"
            "EXPECTED RESULTS — assertive, measurable, present-tense:\n"
            "  - BAD: 'System works as expected'. GOOD: 'HTTP 400 is returned. Response body contains field-level error: Name is required.'\n"
            "scenario_type must be exactly one of: Positive, Negative, Edge Case, Exception Handling.\n"
            "test_case_layer must be exactly one of the layers in allowed_layers.\n"
            "Use each layer only when it adds unique verification value. All array fields must be JSON arrays."
        )

        out: list[dict] = []
        total_acs = len(ac_groups)
        completed = 0
        any_llm_success = False
        started = time.time()

        for (story_id, ac_id), ac_data in ac_groups.items():
            grp_bps = ac_data["blueprints"]
            allowed_layers = sorted({bp["layer_candidates"][0] for bp in grp_bps})

            user = json.dumps({
                "story_id": story_id,
                "story_title": ac_data["story_title"],
                "ac_id": ac_id,
                "ac_text": ac_data["ac_text"],
                "document_excerpt": doc_excerpt,
                "allowed_layers": allowed_layers,
                "seed_blueprints": grp_bps,
                "generation_rules": [
                    "Return JSON with a single key 'test_cases' containing an array.",
                    "Every test case must set 'ac_id' to the ac_id value provided above.",
                    "Generate 5-12 test cases per AC. Always start with at least one Positive (happy-path) test case. Then cover Negative, Edge Case, and Exception Handling variants. Non-functional tests (Security, Performance) come last. Do not pad — every test must add distinct coverage.",
                    "scenario_type must be exactly one of: Positive, Negative, Edge Case, Exception Handling.",
                    "test_suite must be exactly one of: Smoke, Functional, EndToEnd. Default to Functional for all business-rule tests. Use Smoke only for health checks. Use EndToEnd only when the test crosses multiple systems.",
                    "execution_tags: array of zero or more from: Regression, UAT, Parity, Migration. Apply Regression for tests that should re-run after changes.",
                    "classification_rationale: one sentence explaining the test_suite choice.",
                    "Each test case must include: ac_id, title, test_case_layer (from allowed_layers), scenario_type, test_suite, execution_tags (array), classification_rationale, non_functional_type, preconditions (array), test_data (array), steps (array), expected_result (string).",
                    "Titles must be concrete and outcome-specific. BAD: 'Validate AC-01'. GOOD: 'Blank name field returns inline validation error on Save'.",
                    "PRECONDITIONS: system state and user role only. Never actions, never vague.",
                    "TEST DATA: concrete values and identifiers. Never placeholders.",
                    "STEPS: one verb-first action per step. No assertions in steps.",
                    "EXPECTED RESULTS: assertive, present-tense, measurable. No vague language.",
                ],
            }, indent=2)

            try:
                payload = client.generate_json(system, user)
                meta["batch_count"] += 1
                if not meta["raw_preview"]:
                    meta["raw_preview"] = json.dumps(payload, ensure_ascii=False)[:1200]

                improved = payload.get("test_cases", [])
                if not isinstance(improved, list) or not improved:
                    raise ValueError(f"LLM returned no test cases for {story_id}/{ac_id}")

                base_bp = grp_bps[0]
                improved_out: list[dict] = []
                for tc in improved:
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
                    # Map functional_test_type → test_suite if LLM used old field name
                    if not merged.get("test_suite") and merged.get("functional_test_type"):
                        merged["test_suite"] = merged["functional_test_type"]
                    improved_out.append(merged)
                out.extend(improved_out)
                any_llm_success = True

            except Exception as exc:
                # Per-AC fallback: generate offline drafts on demand for this AC only
                meta["fallback_reason"] = f"{ac_id}: {exc}"
                out.extend(self._offline_generate_one(bp) for bp in grp_bps)

            completed += 1
            if progress_callback:
                progress_callback(completed, total_acs, f"A5 {completed}/{total_acs}: {ac_id}")

        meta["response_time_sec"] = round(time.time() - started, 2)
        if any_llm_success:
            meta["used"] = True
            meta["generator_source"] = "online_llm"
        return out, meta

    def execute(self, scenario_blueprints: list[dict], document_text: str, execution_mode: str, llm_config: dict, progress_callback=None) -> dict:
        llm_meta = {"requested": execution_mode == "online", "used": False, "fallback_reason": "", "generator_source": "offline_rules"}
        if execution_mode == "online":
            # Offline drafts are generated lazily inside the online path (only on per-AC LLM failure)
            tests, llm_meta = self._online_generate_from_groups(scenario_blueprints, document_text, llm_config, fail_on_error=True, progress_callback=progress_callback)
        else:
            tests = [self._offline_generate_one(bp) for bp in scenario_blueprints]
        for idx, tc in enumerate(tests, start=1):
            tc["test_case_id"] = f"TC{idx:05d}"
            if not tc.get("automated"):
                tc["automated"] = "May be"
        return {"test_cases": tests, "llm_meta": llm_meta}

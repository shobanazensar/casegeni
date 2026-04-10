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

        # ── Default preconditions from config with Python fallback ────────────
        _default_pres_cfg = self.config.get("default_preconditions", [
            "Application is deployed and accessible in the test environment.",
            "MODULE module is available and the feature under test is enabled.",
        ])
        preconditions = [p.replace("MODULE", module) for p in _default_pres_cfg]

        test_data = [
            f"Domain: {domain}",
            f"Acceptance Criterion: {bp['ac_id']}",
            f"Requirement Text: {ac_text[:120]}",
        ]
        steps = []
        expected = ""
        title = bp.get("title_hint") or f"Validate {bp['ac_id']}"

        # ── Scenario template library — fully config-driven ──────────────────
        library = self.config.get("scenario_templates", {})

        if scenario_key in library:
            selected = library[scenario_key]
        else:
            # ── Seed-type fallback from config ────────────────────────────────
            _fallback_map = self.config.get("seed_type_fallback_map", {
                "Negative": "generic_negative",
                "Exception Handling": "generic_negative",
                "Edge Case": "generic_edge_case",
            })
            fallback_key = _fallback_map.get(seed_type, "generic_positive")
            selected = library.get(fallback_key, library.get("generic_positive", {"pre": [], "steps": [], "expected": ""}))
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
        # Use user-configured max_tokens (default 8192). Each rich test case costs ~550 tokens;
        # 4-8 test cases per AC requires ~2200-4400 tokens — 8192 gives safe headroom.
        # Offline drafts are generated LAZILY — only on LLM failure for a specific AC.
        client = LLMClient(
            model=llm_config.get("model", ""),
            api_key=llm_config.get("api_key", ""),
            base_url=llm_config.get("base_url", ""),
            temperature=llm_config.get("temperature", 0.2),
            max_tokens=llm_config.get("max_tokens", 8192),
            use_json_format=llm_config.get("use_json_format", True),
            ssl_verify=llm_config.get("ssl_verify", True),
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
                    "Generate 4-8 test cases per AC. Always start with at least one Positive (happy-path) test case. Then cover Negative, Edge Case, and Exception Handling variants. Non-functional tests (Security, Performance) come last. Do not pad — every test must add distinct coverage.",
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

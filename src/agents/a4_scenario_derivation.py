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

    @staticmethod
    def _resolve_module(domain_context: dict) -> tuple[str, str]:
        """Return (module, submodule) using module_detection_meta for smarter fallback."""
        candidates = domain_context.get("module_or_submodules") or []
        meta = domain_context.get("module_detection_meta", {})
        source = meta.get("source", "unknown")
        confidence = meta.get("confidence", 1.0)

        # If detection was low-confidence/defaulted, prefer subdomain as module hint
        if source in ("default", "noun_frequency") and confidence < 0.5:
            subdomain = domain_context.get("subdomain") or ""
            if subdomain:
                candidates = [subdomain] + [c for c in candidates if c != subdomain]

        module = candidates[0] if candidates else "General"
        submodule = candidates[1] if len(candidates) > 1 else ""
        return module, submodule

    def _base_blueprint(self, req: dict, domain_context: dict, seed_type: str, focus: str, title_hint: str, layer: str, functional_type: str = "Functional", non_functional_type: str = "", scenario_key: str = "general") -> dict:
        module, submodule = self._resolve_module(domain_context)
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

        # ── Config-driven trigger rules ───────────────────────────────────────
        trigger_rules = self.config.get("scenario_trigger_rules", {})

        if trigger_rules:
            # Config path: generic loop over scenario_trigger_rules
            for _rule in trigger_rules.values():
                kws = _rule.get("keywords", [])
                if not any(k in text_l for k in kws):
                    continue
                req_tt = _rule.get("requires_test_type", "")
                if req_tt and req_tt not in selected_test_types:
                    continue
                for bp_def in _rule.get("blueprints", []):
                    layer = bp_def.get("layer", "")
                    sub_kws = bp_def.get("sub_keywords", [])
                    if sub_kws and not any(k in text_l for k in sub_kws):
                        continue
                    bp_req_tt = bp_def.get("requires_test_type", "")
                    if bp_req_tt and bp_req_tt not in selected_test_types:
                        continue
                    add_if(
                        layer,
                        bp_def.get("seed_type", "Positive"),
                        bp_def.get("focus", ""),
                        bp_def.get("title_hint", ""),
                        bp_def.get("scenario_key", "generic"),
                        functional_type=bp_def.get("functional_type", "Functional"),
                        non_functional_type=bp_def.get("non_functional_type", ""),
                    )
        else:
            # Fallback path: original hardcoded if/any blocks
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

        # ── Generic fallback when no triggers matched ─────────────────────────
        if not results:
            _layer_pref = self.config.get("layer_preference_order", ["UI", "API", "Database", "ETL"])
            preferred = self._layers_allowed(_layer_pref, selected_layers)
            if preferred:
                add(self._base_blueprint(req, domain_context, "Positive", "business_valid_flow", f"Validate {req['ac_id']}", preferred[0], "Functional", "", "generic_positive"))
                if len(preferred) > 1:
                    add(self._base_blueprint(req, domain_context, "Negative", "validation_or_rejection", f"Reject invalid processing for {req['ac_id']}", preferred[1], "Functional", "", "generic_negative"))

        # ── Ensure minimum positive blueprints per configured layers ──────────
        _min_cfg = self.config.get("min_positives_per_layer", {"count": 2, "layers": ["UI", "API"]})
        _min_count = _min_cfg.get("count", 2)
        _min_layers = _min_cfg.get("layers", ["UI", "API"])
        positives_by_layer: dict = {}
        for bp in results:
            if bp.get("seed_type") == "Positive" and not bp.get("non_functional_type"):
                lyr = (bp.get("layer_candidates") or [""])[0]
                positives_by_layer[lyr] = positives_by_layer.get(lyr, 0) + 1
        for lyr in _min_layers:
            if lyr in selected_layers:
                need = max(0, _min_count - positives_by_layer.get(lyr, 0))
                if need >= 1:
                    add(self._base_blueprint(req, domain_context, "Positive", "business_valid_flow",
                        f"Happy path: {req['ac_id']} completed successfully via {lyr} with valid data",
                        lyr, "Functional", "", f"{lyr.lower()}_happy_path_positive"))
                if need >= 2:
                    add(self._base_blueprint(req, domain_context, "Positive", "business_valid_flow",
                        f"Alternative valid input: {req['ac_id']} succeeds with alternate valid data via {lyr}",
                        lyr, "Functional", "", f"{lyr.lower()}_happy_path_alt_positive"))

        # ── NF sweep: one blueprint per selected NF type not yet present ──────
        _nf_to_layer = self.config.get("nf_type_to_layer", {
            "Security": "API", "Performance": "API",
            "Accessibility": "UI", "Compatibility": "UI",
        })
        nf_covered = {bp.get("non_functional_type") for bp in results if bp.get("non_functional_type")}
        _nf_blueprints = {
            "Security":      ("Negative", "non_functional",  f"Unauthorised request for {req['ac_id']} is rejected at API level",              "nf_security_api_generic"),
            "Performance":   ("Positive", "non_functional",  f"Response time for {req['ac_id']} stays within SLA under expected load",          "nf_performance_api_generic"),
            "Accessibility": ("Positive", "non_functional",  f"All UI controls for {req['ac_id']} are keyboard accessible and screen-reader labelled", "nf_accessibility_ui_generic"),
            "Compatibility": ("Positive", "non_functional",  f"Feature for {req['ac_id']} renders correctly across supported browsers and devices",     "nf_compatibility_ui_generic"),
        }
        for nf_type, (seed, focus, hint, key) in _nf_blueprints.items():
            if nf_type in selected_test_types and nf_type not in nf_covered:
                layer = _nf_to_layer.get(nf_type, "API")
                add_if(layer, seed, focus, hint, key, functional_type="", non_functional_type=nf_type)

        # ── Full layer coverage baseline: ≥1 Positive, ≥1 Negative, ≥1 Edge Case per layer ──
        _baseline_cfg = self.config.get("baseline_scenario_types", [
            {"seed_type": "Positive",  "focus": "business_valid_flow",         "hint_prefix": "Happy path",          "key_suffix": "baseline_positive"},
            {"seed_type": "Negative",  "focus": "validation_or_rejection",     "hint_prefix": "Invalid input",       "key_suffix": "baseline_negative"},
            {"seed_type": "Edge Case", "focus": "boundary_and_data_variation", "hint_prefix": "Boundary/edge input", "key_suffix": "baseline_edge"},
        ])
        functional_coverage: dict = {}
        for bp in results:
            if not bp.get("non_functional_type"):
                lyr = (bp.get("layer_candidates") or [""])[0]
                stype = bp.get("seed_type", "")
                functional_coverage.setdefault(lyr, set()).add(stype)
        for lyr in selected_layers:
            covered_stypes = functional_coverage.get(lyr, set())
            for b in _baseline_cfg:
                if b["seed_type"] not in covered_stypes:
                    add(self._base_blueprint(
                        req, domain_context, b["seed_type"], b["focus"],
                        f"{lyr}: {b['hint_prefix']} for {req['ac_id']}",
                        lyr, "Functional", "", f"{lyr.lower()}_{b['key_suffix']}",
                    ))

        return results

    def _online_derive(self, requirements: list[dict], domain_context: dict, selected_layers: list[str], selected_test_types: list[str], llm_config: dict, progress_callback=None) -> list[dict]:
        # A4 blueprints are compact. With the optimised output spec (redundant
        # identity fields stripped from each blueprint), 15 blueprints per AC
        # cost ~100-150 tokens each = 1500-2500 tokens. 3000 gives safe headroom.
        _A4_MAX_TOKENS = 3000
        client = LLMClient(
            model=llm_config.get("model", ""),
            api_key=llm_config.get("api_key", ""),
            base_url=llm_config.get("base_url", ""),
            temperature=llm_config.get("temperature", 0.2),
            max_tokens=min(llm_config.get("max_tokens", _A4_MAX_TOKENS), _A4_MAX_TOKENS),
            use_json_format=llm_config.get("use_json_format", True),
            ssl_verify=llm_config.get("ssl_verify", True),
        )
        if not client.is_configured():
            raise ValueError("LLM configuration incomplete for A4 online mode")

        module, submodule = self._resolve_module(domain_context)

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
            "- Generate at most 15 blueprints per AC. Prioritise distinct, high-value variants over exhaustive lists.\n"
            "- Each blueprint must include ONLY these fields: "
            "seed_type (Positive|Negative|Edge Case|Exception Handling), focus, title_hint, "
            "scenario_key (snake_case), layer_candidates (array, one item from allowed_layers), "
            "functional_test_type, non_functional_type, risk_tags.\n"
            "- Do NOT repeat story_id, story_title, ac_id, ac_text, domain, module or submodule "
            "inside each blueprint — they are already known from the input context.\n"
        )

        all_blueprints: list[dict] = []
        total = len(requirements)
        completed = 0

        for req in requirements:
            story_id = req["story_id"]
            # Wire retry notifications into the progress bar for this AC.
            if progress_callback:
                _ac_label = req["ac_id"]
                _total = total
                _done_ref = [completed]
                def _make_retry_cb(label: str, done_ref: list, tot: int):
                    def _cb(attempt: int, err: str) -> None:
                        progress_callback(done_ref[0], tot, f"⚠️ Retrying {label} (attempt {attempt}): {err[:80]}")
                    return _cb
                client.on_retry = _make_retry_cb(_ac_label, _done_ref, _total)
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
                    "Return JSON with a single key 'scenario_blueprints' containing an array (max 15 items).",
                    "Generate the most distinct, high-value scenario variants for this single AC. Do not pad.",
                ],
            }, indent=2)

            try:
                payload = client.generate_json(system, user_msg)
                raw = payload.get("scenario_blueprints", [])
                if not isinstance(raw, list):
                    raw = []
            except Exception as exc:
                # Propagate the LLM error immediately — no offline fallback.
                # The LLMClient already applied exponential-backoff retries for
                # transient 429/5xx errors before raising here.
                raise RuntimeError(f"LLM failed for {req['story_id']}/{req['ac_id']}: {exc}") from exc

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

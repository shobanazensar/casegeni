from __future__ import annotations
import re
from collections import Counter
from src.agents.base import AgentBase


class A2DomainApp(AgentBase):
    def __init__(self, base_dir):
        super().__init__(base_dir, "A2 Domain and app - Offline.updated.json")

    def execute(self, document_text: str, project_state: str, state_driven_focus: str) -> dict:
        text = document_text.lower()
        keywords = self.config["domain_keywords"]

        # ── Domain scoring ────────────────────────────────────────────────────
        _weights = self.config.get("domain_score_weights", {"primary": 3, "secondary": 1})
        _w_primary   = _weights.get("primary", 3)
        _w_secondary = _weights.get("secondary", 1)

        scores: dict[str, int] = {}
        for domain, rule in keywords.items():
            score = 0
            for term in rule.get("primary", []):
                if term in text:
                    score += _w_primary
            for term in rule.get("secondary", []):
                if term in text:
                    score += _w_secondary
            scores[domain] = score
        primary = max(scores, key=lambda d: scores[d])
        if scores[primary] == 0:
            primary = "generic"

        # ── Output limits ─────────────────────────────────────────────────────
        _limits = self.config.get("output_limits", {
            "module_candidates": 3, "noun_top_n": 4, "roles": 6,
            "process_flows": 5, "domain_signals": 10, "regulations": 6,
        })

        # ── Module detection ──────────────────────────────────────────────────
        # Step 1: Config-driven label regex
        label_synonyms = self.config.get("module_label_synonyms", [
            "module", "sub-module", "submodule", "feature", "component",
            "screen", "form", "page", "section", "service", "system",
            "product", "application", "platform", "epic", "user story", "story"
        ])
        app_labels = set(self.config.get("app_label_synonyms",
                         ["product", "application", "platform", "system"]))
        story_labels = set(self.config.get("story_label_exclusions",
                           ["epic", "user story", "story"]))
        label_pattern = r"(" + "|".join(re.escape(s) for s in label_synonyms) + r")\s*[:\-]\s*(.+)"
        storyish = re.findall(label_pattern, document_text, flags=re.I)

        module_candidates: list[str] = []
        app_name = ""
        for kind, value in storyish:
            kind_l = kind.lower().strip()
            value_s = value.strip()
            if kind_l in app_labels and not app_name:
                app_name = value_s
            elif kind_l not in app_labels and kind_l not in story_labels:
                module_candidates.append(value_s)

        # Step 2: Config-driven inline pattern detection (Enhancement #6)
        if not module_candidates:
            context_patterns = self.config.get("module_context_patterns", [])
            for pat in context_patterns:
                for m in re.findall(pat, document_text):
                    val = (m.strip() if isinstance(m, str) else m).strip()
                    # Strip leading articles
                    val = re.sub(r"^(?:the|a|an)\s+", "", val, flags=re.I).strip()
                    if val and val not in module_candidates:
                        module_candidates.append(val)
            detect_source = "inline_pattern" if module_candidates else ""
        else:
            detect_source = "explicit_label"

        # Step 3: Config-driven module keyword scoring (Enhancement #2)
        mod_scores: dict[str, int] = {}
        if not module_candidates:
            modules_cfg: dict = self.config.get("modules_by_domain", {}).get(primary, {})
            for mod_name, mod_keywords in modules_cfg.items():
                score = sum(1 for kw in mod_keywords if kw in text)
                if score:
                    mod_scores[mod_name] = score
            if mod_scores:
                _mc_limit = _limits.get("module_candidates", 3)
                module_candidates = [m for m, _ in sorted(mod_scores.items(), key=lambda x: -x[1])[:_mc_limit]]
                detect_source = "keyword_scored"

        # Step 4: Last-resort extended noun frequency fallback
        if not module_candidates:
            _fallback_nouns = self.config.get("module_fallback_nouns", [
                "order", "profile", "checkout", "payment", "shipment", "inventory",
                "claims", "patient", "account", "reporting", "notification", "sync",
                "audit", "employee", "payroll", "subscriber", "meter", "permit",
                "student", "trade", "policy", "deposit", "identity", "tenant",
                "reconciliation", "onboarding", "kyc", "grievance", "portal",
                "workflow", "dashboard", "approval", "disbursement", "enrollment",
                "billing", "scheduling", "timesheet", "fulfillment", "returns",
                "catalog", "pricing", "compliance", "monitoring", "ledger",
                "assessment", "registration", "authorization", "provisioning",
            ])
            _noun_pattern = r"\b(" + "|".join(re.escape(n) for n in _fallback_nouns) + r")\b"
            nouns = re.findall(_noun_pattern, text)
            _noun_top_n = _limits.get("noun_top_n", 4)
            module_candidates = [w.title() for w, _ in Counter(nouns).most_common(_noun_top_n)] or ["General"]
            detect_source = "noun_frequency" if module_candidates != ["General"] else "default"

        detect_confidence = round(
            self.config.get("module_detection_confidence", {
                "explicit_label": 0.90, "inline_pattern": 0.75,
                "keyword_scored": 0.70, "noun_frequency": 0.45, "default": 0.20,
            }).get(detect_source, 0.20), 2
        )

        # ── Subdomain detection (Enhancement #3: uses modules_by_domain keywords) ──
        subdomain = None
        sub_scores: dict[str, int] = {}
        modules_cfg_sub: dict = self.config.get("modules_by_domain", {}).get(primary, {})
        for sub in self.config.get("subdomains_by_domain", {}).get(primary, []):
            kw_list = modules_cfg_sub.get(sub, [])
            if kw_list:
                # Score using full keyword vocabulary for this subdomain
                hit = sum(1 for kw in kw_list if kw in text)
            else:
                # Fallback: score using label words
                sub_words = [w for w in re.split(r"[\s/&()\-]+", sub.lower()) if len(w) > 3]
                hit = sum(1 for w in sub_words if w in text)
            if hit:
                sub_scores[sub] = hit
        if sub_scores:
            subdomain = max(sub_scores, key=lambda s: sub_scores[s])

        roles = sorted(set(re.findall(r"As a[n]? ([^,\.\n]+)", document_text, flags=re.I)))[: _limits.get("roles", 6)]
        process_flows = [s.strip() for s in re.findall(r"so that ([^\.\n]+)", document_text, flags=re.I)][: _limits.get("process_flows", 5)]

        # ── module_detection_meta (Enhancement #7) ────────────────────────────
        module_detection_meta = {
            "source": detect_source,
            "confidence": detect_confidence,
            "scored_modules": mod_scores,
        }

        _default_app = self.config.get("default_application_name", "Requirement Driven Product")

        return {
            "project_state": project_state,
            "state_driven_focus": state_driven_focus,
            "primary_domain": primary,
            "secondary_domain": "",
            "subdomain": subdomain,
            "confidence_score": min(0.99, max(0.35, scores.get(primary, 0) / 12 if primary != "generic" else 0.35)),
            "application_or_product": app_name or _default_app,
            "module_or_submodules": module_candidates,
            "module_detection_meta": module_detection_meta,
            "domain_signals": [k for k in (keywords.get(primary) or {}).get("primary", []) if k in text][: _limits.get("domain_signals", 10)],
            "business_entities": module_candidates[:],
            "user_roles": roles,
            "likely_process_flows": process_flows,
            "applicable_regulations": self.config.get("regulations_by_domain", {}).get(primary, [])[:_limits.get("regulations", 6)],
            "domain_test_focus": self.config.get("test_focus_by_domain", {}).get(primary, []) if "test_focus_by_domain" in self.config else [],
            "reasoning": (
                f"Detected domain={primary}, subdomain={subdomain} via rule-based keyword scoring. "
                f"Module detection source='{detect_source}' (confidence={detect_confidence})."
            ),
        }

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
        scores = {}
        for domain, rule in keywords.items():
            score = 0
            for term in rule.get("primary", []):
                if term in text:
                    score += 3
            for term in rule.get("secondary", []):
                if term in text:
                    score += 1
            scores[domain] = score
        primary = max(scores, key=scores.get)
        if scores[primary] == 0:
            primary = "generic"

        storyish = re.findall(r"(epic|user story|story|module|product|application)\s*:\s*(.+)", document_text, flags=re.I)
        module_candidates = []
        app_name = ""
        for kind, value in storyish:
            if kind.lower() in {"product", "application"} and not app_name:
                app_name = value.strip()
            if kind.lower() in {"module"}:
                module_candidates.append(value.strip())
        if not module_candidates:
            nouns = re.findall(r"\b(order|profile|checkout|payment|shipment|inventory|claims|patient|account|reporting|notification|sync|audit)\b", text)
            module_candidates = [w.replace("_", " ").title() for w, _ in Counter(nouns).most_common(4)] or ["General"]
        roles = sorted(set(re.findall(r"As a[n]? ([^,\.\n]+)", document_text, flags=re.I)))[:6]
        process_flows = [s.strip() for s in re.findall(r"so that ([^\.\n]+)", document_text, flags=re.I)][:5]

        return {
            "project_state": project_state,
            "state_driven_focus": state_driven_focus,
            "primary_domain": primary,
            "secondary_domain": "",
            "confidence_score": min(0.99, max(0.35, scores.get(primary, 0) / 12 if primary != "generic" else 0.35)),
            "application_or_product": app_name or "Requirement Driven Product",
            "module_or_submodules": module_candidates,
            "domain_signals": [k for k in (keywords.get(primary) or {}).get("primary", []) if k in text][:10],
            "business_entities": module_candidates[:],
            "user_roles": roles,
            "likely_process_flows": process_flows,
            "applicable_regulations": self.config.get("regulations_by_domain", {}).get(primary, [])[:6],
            "domain_test_focus": self.config.get("testing_focus_by_domain", {}).get(primary, []) if "testing_focus_by_domain" in self.config else [],
            "reasoning": f"Detected domain={primary} using rule-based keyword evidence.",
        }

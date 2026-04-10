from __future__ import annotations
from src.agents.base import AgentBase


# ---------------------------------------------------------------------------
# Dimension weights for the 8-factor offline scoring model
# Each dimension contributes a score in the range noted; total drives P0–P3.
# ---------------------------------------------------------------------------
#
# Dimension               Max pts  Basis
# ─────────────────────── ───────  ──────────────────────────────────────────
# Business Impact             3    revenue / CX / statutory keywords in AC
# Functional Criticality      2    Smoke / EndToEnd / core keyword signals
# Integration & Dep. Risk     2    API / ETL + integration keyword signals
# Data Risk                   2    PII / GDPR / accuracy keywords
# Failure Blast Radius        2    multi-region / multi-role / bulk keywords
# Defect Probability          2    complex logic / legacy project state
# Environment Applicability   1    prod / UAT / critical env tags
# Usage Frequency             1    daily / high-frequency keyword signals
# ─────────────────────────────────────────────────────────────────────────
# Total max = 15
#
# Score → Priority mapping (thresholds tuned to keep P0 selective):
#   score >= 10  → P0 – Must Test  (go-live blocker / compliance / financial)
#   score  7–9   → P1 – High       (key business / critical integration)
#   score  4–6   → P2 – Medium     (secondary flows / limited users)
#   score  0–3   → P3 – Low        (informational / cosmetic / rare edge)


_BUSINESS_IMPACT_KEYWORDS = {
    # statutory / compliance / financial
    "payroll", "invoice", "payment", "billing", "tax", "vat", "gst",
    "statutory", "regulatory", "compliance", "audit", "financial",
    "revenue", "settlement", "refund", "penalty", "sla",
    # customer-experience critical
    "checkout", "order placement", "login", "authentication", "registration",
}

_CRITICALITY_KEYWORDS = {
    "core", "primary", "main", "critical", "essential", "mandatory",
    "must", "required", "key", "primary flow",
}

_INTEGRATION_KEYWORDS = {
    "integration", "upstream", "downstream", "webhook", "callback",
    "third-party", "external system", "api call", "etl", "pipeline",
    "sync", "feed", "interface", "message queue", "event",
}

_DATA_RISK_KEYWORDS = {
    "pii", "gdpr", "personal data", "sensitive", "confidential",
    "ssn", "credit card", "password", "token", "secret", "phi",
    "data accuracy", "data integrity", "corruption", "loss",
    "masked", "encrypted", "anonymised", "de-identified",
}

_BLAST_RADIUS_KEYWORDS = {
    "all users", "all tenants", "every customer", "all regions",
    "bulk", "batch", "mass", "global", "enterprise-wide",
    "cross-module", "end-to-end", "platform",
}

_DEFECT_PROBABILITY_KEYWORDS = {
    "complex", "conditional", "state machine", "state transition",
    "concurrency", "race condition", "async", "retry", "timeout",
    "calculation", "formula", "algorithm", "rounding",
    "unauthorized", "permission", "role-based", "access control",
}

_HIGH_FREQUENCY_KEYWORDS = {
    "daily", "every day", "frequent", "real-time", "always",
    "high volume", "peak", "every transaction", "per request",
}


def _score_test_case(tc: dict, project_state: str) -> tuple[int, str]:
    """Return (score, priority_reason) using the 8-dimension model."""
    ac = (tc.get("ac_text") or "").lower()
    title = (tc.get("title") or "").lower()
    tags = {t.lower() for t in tc.get("tags", [])}
    layer = tc.get("test_case_layer", "")
    scenario = tc.get("scenario_type", "")
    exec_tags = set(tc.get("execution_tags") or [])
    nft = (tc.get("non_functional_type") or "").lower()
    reasons: list[str] = []

    # 1. Business Impact (0–3)
    bi = 0
    if any(k in ac or k in title for k in _BUSINESS_IMPACT_KEYWORDS):
        bi = 2
    if any(k in ac for k in {"payroll", "payment", "invoice", "statutory", "regulatory", "compliance", "revenue"}):
        bi = 3
    if bi:
        reasons.append(f"business-impact={bi}")

    # 2. Functional Criticality (0–2)
    fc = 0
    if "Smoke" in exec_tags or "E2E" in exec_tags or "Integration" in exec_tags:
        fc = 2
    elif any(k in ac or k in title for k in _CRITICALITY_KEYWORDS):
        fc = 1
    if fc:
        reasons.append(f"functional-criticality={fc}")

    # 3. Integration & Dependency Risk (0–2)
    ir = 0
    if layer in {"API", "ETL"}:
        ir += 1
    if any(k in ac or k in title for k in _INTEGRATION_KEYWORDS):
        ir = min(ir + 1, 2)
    if ir:
        reasons.append(f"integration-risk={ir}")

    # 4. Data Risk (0–2)
    dr = 0
    if nft == "security":
        dr = 2
    elif any(k in ac or k in title for k in _DATA_RISK_KEYWORDS):
        dr = 2
    if dr:
        reasons.append(f"data-risk={dr}")

    # 5. Failure Blast Radius (0–2)
    br = 0
    if any(k in ac or k in title for k in _BLAST_RADIUS_KEYWORDS):
        br = 1
    if "E2E" in exec_tags or "Integration" in exec_tags:
        br = min(br + 1, 2)
    if br:
        reasons.append(f"blast-radius={br}")

    # 6. Defect Probability (0–2)
    dp = 0
    if scenario in {"Negative", "Exception Handling"}:
        dp += 1
    if project_state == "Brownfield":
        dp += 1
    if any(k in ac or k in title for k in _DEFECT_PROBABILITY_KEYWORDS):
        dp = min(dp + 1, 2)
    dp = min(dp, 2)
    if dp:
        reasons.append(f"defect-probability={dp}")

    # 7. Environment Applicability (0–1)
    ea = 0
    if "prod" in tags or "production" in tags or "uat" in tags or "critical" in tags:
        ea = 1
    if ea:
        reasons.append(f"env-applicability={ea}")

    # 8. Usage Frequency (0–1)
    uf = 0
    if any(k in ac or k in title for k in _HIGH_FREQUENCY_KEYWORDS):
        uf = 1
    if uf:
        reasons.append(f"usage-frequency={uf}")

    score = bi + fc + ir + dr + br + dp + ea + uf
    reason_str = "; ".join(reasons) if reasons else "low signal across all dimensions"
    return score, reason_str


def _score_to_priority(score: int) -> str:
    if score >= 10:
        return "P0"
    if score >= 7:
        return "P1"
    if score >= 4:
        return "P2"
    return "P3"


class A6Prioritization(AgentBase):
    def __init__(self, base_dir):
        super().__init__(base_dir, "A6 Prioritization - Offline.updated.json")

    def execute(self, test_cases: list[dict], project_state: str) -> dict:
        for tc in test_cases:
            score, reason = _score_test_case(tc, project_state)
            tc["priority"] = _score_to_priority(score)
            tc["priority_reason"] = reason
            tc["risk_score"] = score

            layer = tc.get("test_case_layer", "")
            tc["automation_hint"] = (
                "Yes" if layer in {"API", "Database", "ETL"}
                else ("Maybe" if layer == "UI" else "No")
            )
            tc["automated"] = tc["automation_hint"]
        return {"test_cases": test_cases}

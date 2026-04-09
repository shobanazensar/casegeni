from __future__ import annotations
import re


class A1ProjectState:
    legacy_terms = ["legacy", "existing system", "migrate", "migration", "modernization"]
    existing_terms = ["enhancement", "change request", "modify", "update existing"]

    def execute(self, document_text: str) -> dict:
        text = document_text.lower()
        if any(t in text for t in self.legacy_terms):
            return {"project_state": "Legacy", "state_driven_focus": "Risk containment"}
        if any(t in text for t in self.existing_terms):
            return {"project_state": "Brownfield", "state_driven_focus": "Impact analysis"}
        return {"project_state": "Greenfield", "state_driven_focus": "Discovery"}
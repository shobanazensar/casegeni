from __future__ import annotations
import re


class A1ProjectState:
    brownfield_terms = [
        "legacy", "existing system", "migrate", "migration", "modernization",
        "enhancement", "change request", "modify", "update existing",
    ]

    def execute(self, document_text: str) -> dict:
        text = document_text.lower()
        if any(t in text for t in self.brownfield_terms):
            return {"project_state": "Brownfield", "state_driven_focus": "Impact analysis"}
        return {"project_state": "Greenfield", "state_driven_focus": "Discovery"}
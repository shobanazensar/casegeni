from __future__ import annotations
import re
from src.agents.base import AgentBase


class A3Requirements(AgentBase):
    def __init__(self, base_dir):
        super().__init__(base_dir, "A3 Requirements - Offline.updated.json")

    def _extract_acceptance_lines(self, block: str) -> list[str]:
        lines = [line.rstrip() for line in block.splitlines()]
        ac_lines = []
        in_ac_section = False
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            lower = line.lower()
            if lower.startswith("acceptance criteria") or lower.startswith("acceptance criterion"):
                in_ac_section = True
                continue
            if in_ac_section:
                if re.match(r"^\d+[\).:-]?\s+", line):
                    ac_lines.append(re.sub(r"^\d+[\).:-]?\s*", "", line).strip())
                    continue
                if re.match(r"^ac\d+\s*:\s*", line, flags=re.I):
                    ac_lines.append(re.sub(r"^ac\d+\s*:\s*", "", line, flags=re.I).strip())
                    continue
                # Continuation of previous AC line
                if ac_lines and not re.match(r"^(story|user story|epic)\s*:", line, flags=re.I):
                    ac_lines[-1] = f"{ac_lines[-1]} {line}".strip()
        if ac_lines:
            return ac_lines
        # fallback extraction for inline AC style documents
        ac_lines = re.findall(r"AC\d+\s*:\s*(.+)", block, flags=re.I)
        if ac_lines:
            return [x.strip() for x in ac_lines]
        return [line.strip() for line in block.splitlines() if line.strip().lower().startswith(("must", "should", "system should", "user should"))]

    def execute(self, document_text: str) -> dict:
        stories = []
        epic_match = re.search(r"Epic\s*:\s*(.+)", document_text, flags=re.I)
        epic_title = epic_match.group(1).strip() if epic_match else ""

        story_blocks = re.split(r"(?=User Story\s*:|Story\s*:)", document_text, flags=re.I)
        parsed_story_blocks = [b.strip() for b in story_blocks if re.search(r"(User Story|Story)\s*:", b, flags=re.I)]

        if not parsed_story_blocks and re.search(r"As a ", document_text, flags=re.I):
            parsed_story_blocks = [document_text]

        for idx, block in enumerate(parsed_story_blocks or [document_text], start=1):
            story_title_match = re.search(r"(?:User Story|Story)\s*:\s*(.+)", block, flags=re.I)
            if story_title_match:
                story_title = story_title_match.group(1).strip()
            else:
                first_line = next((ln.strip() for ln in block.splitlines() if ln.strip()), f"Story {idx}")
                story_title = first_line if len(first_line) < 180 else f"Story {idx}"
            ac_lines = self._extract_acceptance_lines(block)
            acs = []
            for j, ac in enumerate(ac_lines, start=1):
                acs.append({
                    "story_id": f"ST{idx}",
                    "story_title": story_title,
                    "ac_id": f"ST{idx}-AC{j}",
                    "text": ac,
                })
            stories.append({
                "story_id": f"ST{idx}",
                "story_title": story_title,
                "epic_title": epic_title,
                "acceptance_criteria": acs,
            })

        all_acs = [ac for s in stories for ac in s["acceptance_criteria"]]
        return {
            "epic_title": epic_title,
            "stories": stories,
            "requirements": all_acs,
            "summary": {"story_count": len(stories), "ac_count": len(all_acs)}
        }

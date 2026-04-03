from __future__ import annotations
import json
import re
from src.agents.base import AgentBase


class A3Requirements(AgentBase):
    def __init__(self, base_dir):
        super().__init__(base_dir, "A3 Requirements - Offline.updated.json")

    # ------------------------------------------------------------------
    # Acceptance-criteria extraction
    # ------------------------------------------------------------------

    _AC_SECTION_HEADERS = re.compile(
        r"^(acceptance\s+criteri[ao]n?|conditions?|criteria|requirements?|"
        r"definition\s+of\s+done|dod|constraints?|checklist|expected\s+results?|"
        r"success\s+criteria|given[- ]when[- ]then)\s*:?\s*$",
        flags=re.I,
    )
    _BDD_PREFIX = re.compile(r"^(given|when|then|and|but)\b", flags=re.I)
    _STORY_BOUNDARY = re.compile(
        r"^(story|user\s+story|epic|feature|scenario|us[\s-]?\d+|#{1,4})\s*[:\s]",
        flags=re.I,
    )

    # ------------------------------------------------------------------
    # Pre-processing: normalise markdown bold/italic markup
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_markup(text: str) -> str:
        """Strip markdown bold/italic markers (**text**, *text*, __text__, _text_)."""
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # **bold**
        text = re.sub(r"__(.+?)__", r"\1", text)       # __bold__
        text = re.sub(r"\*(.+?)\*", r"\1", text)       # *italic*
        text = re.sub(r"_(.+?)_", r"\1", text)         # _italic_
        return text

    def _extract_acceptance_lines(self, block: str) -> list[str]:
        lines = [line.rstrip() for line in block.splitlines()]
        ac_lines: list[str] = []
        in_ac_section = False

        for raw in lines:
            line = raw.strip()
            if not line:
                continue

            # Detect AC section headers (wide vocabulary)
            if self._AC_SECTION_HEADERS.match(line):
                in_ac_section = True
                continue

            # BDD lines are always treated as ACs
            if self._BDD_PREFIX.match(line):
                ac_lines.append(line)
                in_ac_section = True
                continue

            if in_ac_section:
                # Stop at next story/section boundary
                if self._STORY_BOUNDARY.match(line):
                    break

                # ACn: format
                if re.match(r"^ac\d+\s*:\s*", line, flags=re.I):
                    ac_lines.append(re.sub(r"^ac\d+\s*:\s*", "", line, flags=re.I).strip())
                    continue

                # Numbered: "1. " / "1) " / "1: "
                if re.match(r"^\d+[\).:-]\s+", line):
                    ac_lines.append(re.sub(r"^\d+[\).:-]\s*", "", line).strip())
                    continue

                # Bullet: "- " / "* " / "• "
                if re.match(r"^[-*\u2022]\s+", line):
                    ac_lines.append(re.sub(r"^[-*\u2022]\s+", "", line).strip())
                    continue

                # Checkbox: "[ ] " / "[x] " / "[✓] "
                if re.match(r"^\[[ x\u2713]\]\s+", line, flags=re.I):
                    ac_lines.append(re.sub(r"^\[[ x\u2713]\]\s+", "", line, flags=re.I).strip())
                    continue

                # Continuation of previous AC (plain text)
                if ac_lines:
                    ac_lines[-1] = f"{ac_lines[-1]} {line}".strip()

        if ac_lines:
            return ac_lines

        # Fallback 1: inline "AC1: text" anywhere in the block
        inline = re.findall(r"AC\d+\s*:\s*(.+)", block, flags=re.I)
        if inline:
            return [x.strip() for x in inline]

        # Fallback 2: BDD lines anywhere in the block
        bdd = re.findall(r"^(?:Given|When|Then|And|But)\b.+", block, flags=re.I | re.M)
        if bdd:
            return [x.strip() for x in bdd]

        # Fallback 3: bullet points anywhere in the block
        bullets = re.findall(r"^[-*\u2022]\s+(.+)", block, flags=re.M)
        if bullets:
            return [x.strip() for x in bullets]

        # Fallback 4: "must" / "should" lines (bare or with "system/user" prefix)
        must_re = re.compile(
            r"^(?:(?:the\s+)?(?:system|user|application|service)\s+)?(?:must|should)\b",
            flags=re.I,
        )
        return [
            ln.strip()
            for ln in block.splitlines()
            if must_re.match(ln.strip())
        ]

    # ------------------------------------------------------------------
    # Story-block splitting
    # ------------------------------------------------------------------

    def _split_into_story_blocks(self, text: str) -> list[str]:
        """Split document into individual story blocks, supporting many input formats."""

        # 1. Markdown headings (h1–h3) – check first so "### Title\nUser Story:" docs keep heading+content together
        if re.search(r"^#{1,3} \S", text, flags=re.M):
            blocks = re.split(r"(?=^#{1,3} )", text, flags=re.M)
            parsed = [b.strip() for b in blocks if b.strip()]
            if len(parsed) > 1:
                return parsed

        # 2. Standard: "User Story: ..." or "Story: ..."
        blocks = re.split(r"(?=(?:User\s+Story|Story)\s*:)", text, flags=re.I)
        parsed = [b.strip() for b in blocks if re.search(r"(?:User\s+Story|Story)\s*:", b, flags=re.I)]
        if parsed:
            return parsed

        # 3. Gherkin: "Feature: ..." or "Scenario: ..."
        if re.search(r"^(?:Feature|Scenario)\s*:", text, flags=re.I | re.M):
            blocks = re.split(r"(?=^(?:Feature|Scenario)\s*:)", text, flags=re.I | re.M)
            parsed = [b.strip() for b in blocks if re.search(r"(?:Feature|Scenario)\s*:", b, flags=re.I)]
            if parsed:
                return parsed

        # 4. Jira/ID style: "US-123:", "US 1:", "US1:"
        if re.search(r"^US[\s-]?\d+\s*:", text, flags=re.I | re.M):
            blocks = re.split(r"(?=^US[\s-]?\d+\s*:)", text, flags=re.I | re.M)
            parsed = [b.strip() for b in blocks if re.search(r"^US[\s-]?\d+\s*:", b, flags=re.I | re.M)]
            if parsed:
                return parsed

        # 5. Numbered story list: "1. As a ..." / "1) As a ..."
        if re.search(r"^\d+[\).]\s+(?:As\s+an?\b|The\s+system|When\s+)", text, flags=re.I | re.M):
            blocks = re.split(r"(?=^\d+[\).]\s+)", text, flags=re.M)
            parsed = [b.strip() for b in blocks if b.strip()]
            if len(parsed) > 1:
                return parsed

        # 6. Single "As a" narrative or any plain text – treat as one story
        return [text]

    # ------------------------------------------------------------------
    # Story title extraction
    # ------------------------------------------------------------------

    def _extract_story_title(self, block: str, idx: int) -> str:
        """Extract a story title from a block, supporting many formats."""
        # Standard – only use if there is actual title text on the same line after the colon
        m = re.search(r"(?:User\s+Story|Story)\s*:[ \t]*(.+)", block, flags=re.I)
        if m and m.group(1).strip():
            return m.group(1).strip()
        # Gherkin
        m = re.search(r"(?:Feature|Scenario)\s*:[ \t]*(.+)", block, flags=re.I)
        if m and m.group(1).strip():
            return m.group(1).strip()
        # Jira ID: "US-123: Title"
        m = re.search(r"(US[\s-]?\d+)\s*:[ \t]*(.+)", block, flags=re.I)
        if m and m.group(2).strip():
            return f"{m.group(1).strip()}: {m.group(2).strip()}"
        # Markdown heading: "## Title" or "### 1. Title"
        m = re.search(r"^#{1,3}\s+(.+)", block, flags=re.M)
        if m:
            return re.sub(r"\*+", "", m.group(1)).strip()
        # First non-empty line (if short enough)
        first = next((ln.strip() for ln in block.splitlines() if ln.strip()), f"Story {idx}")
        return first if len(first) < 180 else f"Story {idx}"

    # ------------------------------------------------------------------
    # JSON input handling
    # ------------------------------------------------------------------

    def _parse_json_input(self, document_text: str) -> list[dict] | None:
        """
        Parse structured JSON input.  Supports arrays or single objects with
        common key names for title, acceptance criteria, and epic.
        Returns None when the input is not valid JSON.
        """
        try:
            data = json.loads(document_text.strip())
        except (json.JSONDecodeError, ValueError):
            return None

        items = data if isinstance(data, list) else [data]
        stories: list[dict] = []

        for idx, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue

            story_id = f"ST{idx}"
            title = (
                item.get("title")
                or item.get("story_title")
                or item.get("name")
                or item.get("summary")
                or str(item.get("description", ""))[:80]
                or f"Story {idx}"
            )
            epic_title = item.get("epic") or item.get("epic_title") or ""

            acs_raw = (
                item.get("acceptance_criteria")
                or item.get("criteria")
                or item.get("ac")
                or item.get("conditions")
                or []
            )
            if isinstance(acs_raw, str):
                acs_raw = [ln.strip() for ln in re.split(r"[\n;]", acs_raw) if ln.strip()]

            acs = [
                {
                    "story_id": story_id,
                    "story_title": title,
                    "ac_id": f"{story_id}-AC{j}",
                    "text": (ac_text if isinstance(ac_text, str) else str(ac_text)).strip(),
                }
                for j, ac_text in enumerate(acs_raw, start=1)
            ]

            stories.append({
                "story_id": story_id,
                "story_title": title,
                "epic_title": epic_title,
                "acceptance_criteria": acs,
            })

        return stories if stories else None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------


    def execute(self, document_text: str) -> dict:
        # --- Structured JSON input (check before any text pre-processing) ---
        json_stories = self._parse_json_input(document_text)
        if json_stories:
            all_acs = [ac for s in json_stories for ac in s["acceptance_criteria"]]
            epic_title = next((s["epic_title"] for s in json_stories if s["epic_title"]), "")
            return {
                "epic_title": epic_title,
                "stories": json_stories,
                "requirements": all_acs,
                "summary": {"story_count": len(json_stories), "ac_count": len(all_acs)},
            }

        # Normalise markdown bold/italic markers (e.g. **User Story:** → User Story:)
        # Only applied to non-JSON text to avoid corrupting structured data.
        document_text = self._strip_markup(document_text)

        # --- Text / Markdown / Gherkin / plain input ---
        epic_match = re.search(r"Epic\s*:\s*(.+)", document_text, flags=re.I)
        epic_title = epic_match.group(1).strip() if epic_match else ""

        story_blocks = self._split_into_story_blocks(document_text)

        stories: list[dict] = []
        for idx, block in enumerate(story_blocks, start=1):
            story_title = self._extract_story_title(block, idx)
            ac_lines = self._extract_acceptance_lines(block)
            acs = [
                {
                    "story_id": f"ST{idx}",
                    "story_title": story_title,
                    "ac_id": f"ST{idx}-AC{j}",
                    "text": ac,
                }
                for j, ac in enumerate(ac_lines, start=1)
            ]
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
            "summary": {"story_count": len(stories), "ac_count": len(all_acs)},
        }

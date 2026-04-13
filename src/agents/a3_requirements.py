from __future__ import annotations
import json
import re
from src.agents.base import AgentBase


class A3Requirements(AgentBase):
    def __init__(self, base_dir):
        super().__init__(base_dir, "A3 Requirements - Offline.updated.json")
        self._build_patterns()

    def _build_patterns(self) -> None:
        """Build compiled regex patterns from config, falling back to hardcoded defaults."""

        # AC section header keywords
        _ac_kws = self.config.get("ac_section_header_keywords", [
            "acceptance criteria", "acceptance criterion", "acceptance criterias",
            "conditions", "condition", "criteria", "requirements", "requirement",
            "definition of done", "dod", "constraints", "constraint", "checklist",
            "expected results", "expected result", "success criteria", "success criterion",
            "given-when-then", "given when then",
            "acs", "ac",
            "test conditions", "test condition", "test criteria", "test criterion",
            "verify that", "validation criteria", "validation criterion",
        ])
        # Build regex: normalise spaces→\s+ and hyphens→[\s\-]+ inside each term.
        # Split on whitespace/hyphens first, escape each word separately, then rejoin,
        # so re.escape never mangles the separator characters.
        def _kw_to_pattern(kw: str) -> str:
            parts = re.split(r"[ \-]+", kw)
            return r"[\s\-]+".join(re.escape(p) for p in parts)
        _ac_alts = "|".join(_kw_to_pattern(k) for k in _ac_kws)
        self._AC_SECTION_HEADERS = re.compile(
            r"^(" + _ac_alts + r")\s*:?\s*$", flags=re.I
        )

        # BDD prefixes
        _bdd = self.config.get("bdd_prefixes", ["given", "when", "then", "and", "but"])
        self._BDD_PREFIX = re.compile(
            r"^(" + "|".join(re.escape(p) for p in _bdd) + r")\b", flags=re.I
        )

        # Story boundary keywords
        _boundary = self.config.get("story_boundary_keywords",
                                    ["story", "user story", "epic", "feature", "scenario"])
        _boundary_alts = "|".join(re.escape(k).replace(r"\ ", r"\s+") for k in _boundary)
        self._STORY_BOUNDARY = re.compile(
            r"^(" + _boundary_alts + r"|us[\s-]?\d+|user\s+story[\s-]?\d+|story[\s-]?\d+|st[\s-]?\d+|#{1,4})\s*[:\s]", flags=re.I
        )

    # ------------------------------------------------------------------
    # Acceptance-criteria extraction
    # ------------------------------------------------------------------

    # Class-level defaults (used if __init__ is bypassed, e.g. in tests)
    _AC_SECTION_HEADERS = re.compile(
        r"^(acceptance\s+criteri[ao]n?(?:s)?|conditions?|criteria|requirements?|"
        r"definition\s+of\s+done|dod|constraints?|checklist|expected\s+results?|"
        r"success\s+criter(?:ia|ion)|given[- ]when[- ]then|"
        r"acs?|test\s+conditions?|test\s+criter(?:ia|ion)|"
        r"verify\s+that|validation\s+criter(?:ia|ion))\s*:?\s*$",
        flags=re.I,
    )
    _BDD_PREFIX = re.compile(r"^(given|when|then|and|but)\b", flags=re.I)
    _STORY_BOUNDARY = re.compile(
        r"^(story[\s-]?\d*|user\s+story[\s-]?\d*|epic[\s-]?\d*|feature|scenario|"
        r"us[\s-]?\d+|st[\s-]?\d+|#{1,4})\s*[:\s]",
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

                # ACn: / AC n: / AC-n: / AC.n: formats
                if re.match(r"^ac[\s.\-]?\d+\s*:\s*", line, flags=re.I):
                    ac_lines.append(re.sub(r"^ac[\s.\-]?\d+\s*:\s*", "", line, flags=re.I).strip())
                    continue

                # Numbered: "1. " / "1) " / "1: " / "1- "
                if re.match(r"^\d+[\).:-]\s+", line):
                    ac_lines.append(re.sub(r"^\d+[\).:-]\s*", "", line).strip())
                    continue

                # Parenthesis-only: "(1) " / "(2) "
                if re.match(r"^\(\d+\)\s+", line):
                    ac_lines.append(re.sub(r"^\(\d+\)\s*", "", line).strip())
                    continue

                # Alpha list: "a. " / "b) " (single letter only, to avoid matching sentences)
                if re.match(r"^[a-z][\).:]\s+", line, flags=re.I):
                    ac_lines.append(re.sub(r"^[a-z][\).:]\s*", "", line, flags=re.I).strip())
                    continue

                # Roman numerals: "i. " / "ii. " / "iii. " / "iv. " / "v. " etc.
                if re.match(r"^(?:i{1,3}|iv|vi{0,3}|ix|xi{0,3}|x)[\).:]\s+", line, flags=re.I):
                    ac_lines.append(re.sub(r"^[^\s.]+[\).:]\s*", "", line).strip())
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

        # Fallback 1: inline "AC1: / AC 1: / AC-1: / AC.1: text" anywhere in the block
        inline = re.findall(r"AC[\s.\-]?\d+\s*:\s*(.+)", block, flags=re.I)
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

        # Fallback 3b: numbered list anywhere in the block
        numbered = re.findall(r"^\d+[\).:-]\s+(.+)", block, flags=re.M)
        if numbered:
            return [x.strip() for x in numbered]

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

        # 2. Standard: "User Story: ..." / "Story: ..." / "User Story 1: ..." / "Story 1: ..."
        blocks = re.split(r"(?=(?:User\s+Story|Story)[\s-]?\d*\s*:)", text, flags=re.I)
        parsed = [b.strip() for b in blocks if re.search(r"(?:User\s+Story|Story)[\s-]?\d*\s*:", b, flags=re.I)]
        if parsed:
            return parsed

        # 3. Gherkin: "Feature: ..." or "Scenario: ..."
        if re.search(r"^(?:Feature|Scenario)\s*:", text, flags=re.I | re.M):
            blocks = re.split(r"(?=^(?:Feature|Scenario)\s*:)", text, flags=re.I | re.M)
            parsed = [b.strip() for b in blocks if re.search(r"(?:Feature|Scenario)\s*:", b, flags=re.I)]
            if parsed:
                return parsed

        # 4. Jira/ID style: "US-123:", "US 1:", "US1:", "ST-1:", "ST1:"
        if re.search(r"^(?:US|ST)[\s-]?\d+\s*:", text, flags=re.I | re.M):
            blocks = re.split(r"(?=^(?:US|ST)[\s-]?\d+\s*:)", text, flags=re.I | re.M)
            parsed = [b.strip() for b in blocks if re.search(r"^(?:US|ST)[\s-]?\d+\s*:", b, flags=re.I | re.M)]
            if parsed:
                return parsed

        # 5. Numbered story list: "1. As a ..." / "1) As a ..."
        if re.search(r"^\d+[\).\]]\s+(?:As\s+an?\b|The\s+system|When\s+)", text, flags=re.I | re.M):
            blocks = re.split(r"(?=^\d+[\).]\s+)", text, flags=re.M)
            parsed = [b.strip() for b in blocks if b.strip()]
            if len(parsed) > 1:
                return parsed

        # 5b. Plain numbered list (e.g. "1. Login feature") — only when most blocks contain an AC header,
        #     to avoid treating numbered prose as story boundaries.
        _ac_hdr_re = re.compile(
            r"^(?:acceptance\s+criteri[ao]n?(?:s)?|acs?|conditions?|criteria|requirements?|"
            r"definition\s+of\s+done|dod|constraints?|checklist|expected\s+results?|"
            r"success\s+criter(?:ia|ion)|test\s+conditions?|test\s+criter(?:ia|ion)|"
            r"verify\s+that|validation\s+criter(?:ia|ion))\s*:?\s*$",
            flags=re.I | re.M,
        )
        if re.search(r"^\d+[\).\]]\s+\S", text, flags=re.M):
            candidate_blocks = re.split(r"(?=^\d+[\).\]]\s+)", text, flags=re.M)
            candidate_blocks = [b.strip() for b in candidate_blocks if b.strip()]
            if len(candidate_blocks) > 1:
                blocks_with_ac = sum(1 for b in candidate_blocks if _ac_hdr_re.search(b))
                if blocks_with_ac > 0 and blocks_with_ac >= len(candidate_blocks) // 2:
                    return candidate_blocks

        # 6. Single "As a" narrative or any plain text – treat as one story
        return [text]

    # ------------------------------------------------------------------
    # Story title extraction
    # ------------------------------------------------------------------

    def _extract_story_title(self, block: str, idx: int) -> str:
        """Extract a story title from a block, supporting many formats."""
        # Standard with optional number: "User Story: / User Story 1: / Story: / Story 1: / Story-1:"
        m = re.search(r"(?:User\s+Story|Story)[\s-]?\d*\s*:[ \t]*(.+)", block, flags=re.I)
        if m and m.group(1).strip():
            return m.group(1).strip()
        # Gherkin
        m = re.search(r"(?:Feature|Scenario)\s*:[ \t]*(.+)", block, flags=re.I)
        if m and m.group(1).strip():
            return m.group(1).strip()
        # Jira-style: "US-123: Title" or "ST-1: Title" or "ST1: Title"
        m = re.search(r"((?:US|ST)[\s-]?\d+)\s*:[ \t]*(.+)", block, flags=re.I)
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

        # Load key aliases from config (fallback to hardcoded defaults)
        _aliases = self.config.get("json_input_key_aliases", {
            "title": ["title", "story_title", "name", "summary", "user_story", "description", "heading"],
            "epic_title": ["epic", "epic_title", "epic_name", "epic_summary"],
            "acceptance_criteria": [
                "acceptance_criteria", "criteria", "ac", "conditions",
                "acs", "ac_list", "criteria_list", "acceptance_conditions",
            ],
        })

        def _pick(item: dict, aliases_key: str, fallback=None):
            """Return first matching value from item using aliases for the given key."""
            for k in _aliases.get(aliases_key, [aliases_key]):
                if k in item:
                    return item[k]
            return fallback

        _id_prefix = self.config.get("story_id_prefix", "ST")

        for idx, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue

            story_id = f"{_id_prefix}{idx}"
            title = (
                _pick(item, "title")
                or str(_pick(item, "title", item.get("description", "")))[:80]
                or f"Story {idx}"
            )
            epic_title = _pick(item, "epic_title") or ""

            acs_raw = _pick(item, "acceptance_criteria") or []
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
        # Matches: "Epic:", "Epic 1:", "Epic-1:", "EPIC-1:", "Epic Title:", "Epic Name:", "Epic Summary:"
        epic_match = re.search(
            r"Epic\s*(?:Title|Name|Summary|[\w-]*\d+)?\s*:\s*(.+)",
            document_text, flags=re.I
        )
        epic_title = epic_match.group(1).strip() if epic_match else ""

        story_blocks = self._split_into_story_blocks(document_text)

        _id_prefix = self.config.get("story_id_prefix", "ST")
        _role_patterns = self.config.get("role_extraction_patterns", [r"As a[n]? ([^,\.\n]+)"])

        stories: list[dict] = []
        for idx, block in enumerate(story_blocks, start=1):
            story_title = self._extract_story_title(block, idx)
            ac_lines = self._extract_acceptance_lines(block)
            story_id = f"{_id_prefix}{idx}"
            acs = [
                {
                    "story_id": story_id,
                    "story_title": story_title,
                    "ac_id": f"{story_id}-AC{j}",
                    "text": ac,
                }
                for j, ac in enumerate(ac_lines, start=1)
            ]
            stories.append({
                "story_id": story_id,
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

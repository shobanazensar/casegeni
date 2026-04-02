# Enterprise Test Case Generation Agent

A robust multi-agent, enterprise-ready test case generation system supporting:
- **Offline mode**: rule-driven deterministic generation
- **Online mode**: OpenAI-compatible LLM generation with RAG context reduction
- **User story / multiple stories / epic inputs**
- **Traceability, reviewer, dashboard, and export**
- **Lightweight blue-themed Streamlit UI**
- **CLI execution**

## Architecture

Agents:
- **A0 Orchestrator** — validate input, set run config, init artifacts
- **A1 Project State** — classify `New / Existing / Legacy`
- **A2 Domain & App** — detect domain, app/product, module, roles, process, regulations
- **A3 Requirements** — parse stories and ACs, extract validations and actors
- **A4 Scenario Derivation** — derive scenarios using EP/BVA/state/pairwise/domain flows
- **A5 Test Generation** — generate execution-ready tests
- **A6 Prioritization** — assign P1..P4 and automation hint
- **A7 Optimization** — deduplicate, split smoke/regression, enforce cap
- **A8 Traceability** — AC ↔ tests matrix and gaps
- **A9 Reviewer** — validate schema/classifications and score quality
- **A10 Dashboard** — stakeholder-friendly summary and readiness view

## RAG & cost control

The solution uses a **retrieval-first approach** so the LLM receives only the most relevant context:
1. Document chunking
2. Lightweight embedding/retrieval adapter
3. Top-k context selection per stage
4. Per-agent focused prompting instead of one giant prompt
5. Optional local `sentence-transformers`; fallback lexical retriever if unavailable

## Input formats

Supported input styles:
1. One user story with multiple acceptance criteria
2. Multiple user stories, each with ACs
3. Epics with stories and ACs

Accepted file types:
- `.txt`
- `.md`
- `.json`

## Run UI

```bash
pip install -r requirements.txt
streamlit run app.py
```

UI features:
- Execution mode: Offline / Online
- Reviewer mode: Offline / Online
- Layer selection
- Test type selection
- Model / API key / Base URL (shown only for Online)
- Temperature / max tokens with defaults from code
- Tabs: Test Cases, Traceability, Reviewer, Dashboard

## Run CLI

```bash
python cli.py --input sample_inputs/epic_sample.md --execution-mode offline --reviewer-mode offline --layers UI API Database "ETL Integration" E2E --test-types Functional Smoke Sanity Regression Performance Security Accessibility Compatibility --output-dir outputs
```

### Online mode example

```bash
python cli.py --input sample_inputs/story_sample.md --execution-mode online --reviewer-mode online --model gpt-4.1-mini --api-key YOUR_KEY --base-url https://api.openai.com/v1 --temperature 0.2 --max-tokens 1800 --output-dir outputs
```

## Output

Each run creates a timestamped folder with:
- `manifest.json`
- `test_cases.json`
- `traceability.json`
- `review_summary.json`
- `dashboard.json`
- `dashboard.html`
- `test_cases.xlsx`

## Notes
- Offline mode is deterministic and suitable for secure or air-gapped environments.
- Online mode uses focused prompts and retrieved context to preserve quality while controlling token cost.
- Hybrid mode is intentionally omitted per requirement.


## Recent updates
- Schema guardrail added after A5 to fix list/string Arrow issues in LLM mode.
- Test cases are now ordered by storyId and acId.
- Traceability and reviewer tabs are rendered as readable tables.
- Excel download and agent output downloads added in UI.
- UI tags use a subtle blue theme.

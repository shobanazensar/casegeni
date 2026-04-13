from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
import streamlit as st
from src.pipeline import TestCasePipeline

st.set_page_config(page_title="Enterprise Test Case Agent", layout="wide")

BLUE_CSS = """
<style>
.stApp { background-color: #f7faff; }
.block-container { padding-top: 1.1rem; padding-bottom: 2rem; }
h1, h2, h3 { color: #123b73; }
.stTabs [data-baseweb="tab-list"] { gap: 8px; }
.stTabs [data-baseweb="tab"] {
    background: #dbe8f8; color: #204c84; border-radius: 10px 10px 0 0;
    padding: 10px 18px; font-weight: 600; border: 1px solid #bfd4ee;
}
.stTabs [aria-selected="true"] { background: #123b73 !important; color: white !important; }
div.stButton > button, .stDownloadButton > button {
    background: #123b73 !important; color: white !important; border-radius: 10px; border: none;
}
[data-baseweb="tag"] { background-color: #eaf2fb !important; color: #355b87 !important; border: 1px solid #cbdcf0 !important; }
.metric-card { background: white; border: 1px solid #d7e4f7; border-radius: 14px; padding: 14px; }
.info-card { background: #ffffff; border: 1px solid #d7e4f7; border-radius: 12px; padding: 10px 14px; margin-bottom: 12px; }
.small-note { color: #5d6f86; font-size: 0.92rem; }
</style>
"""
st.markdown(BLUE_CSS, unsafe_allow_html=True)

st.title("Enterprise Test Case Generation Agent")
pipeline = TestCasePipeline(base_dir=Path(__file__).resolve().parent)

with st.sidebar:
    st.header("Execution")
    execution_mode = st.selectbox("Execution mode", ["offline", "online"], index=0)
    reviewer_mode = "offline"
    selected_layers = st.multiselect(
        "Test layers",
        ["UI", "API", "Database", "ETL"],
        default=["UI", "API", "Database", "ETL"],
    )
    selected_test_types = st.multiselect(
        "Test types",
        ["Functional", "Non-Functional"],
        default=["Functional", "Non-Functional"],
        help="Functional: business rules and AC coverage. Non-Functional: Security, Performance, Compatibility tests.",
    )
    selected_nf_subtypes = st.multiselect(
        "Non-functional subtypes",
        ["Security", "Performance", "Compatibility"],
        default=["Security"],
        help="Which non-functional subtypes to generate. Active when Non-Functional test type is selected.",
    )
    selected_exec_tags = st.multiselect(
        "Execution tags",
        ["Smoke", "E2E", "Integration", "Regression", "UAT", "Parity", "Migration"],
        default=["Smoke", "Regression"],
        help="Execution tags applied to tests. Smoke: post-deploy health checks. E2E: cross-system flow. Integration: cross-service. Regression: re-run after changes.",
    )
    # Only include NF subtypes when the "Non-Functional" test type checkbox is actually checked.
    # Without this guard, NF subtypes bleed through even when Non-Functional is deselected.
    selected_types_combined = (
        (["Functional"] if "Functional" in selected_test_types else []) +
        (selected_nf_subtypes if "Non-Functional" in selected_test_types else [])
    )
    temperature = st.number_input("Temperature", min_value=0.0, max_value=1.5, value=0.2, step=0.05)
    max_tokens = st.number_input("Max tokens", min_value=256, max_value=64000, value=8192, step=128)
    if max_tokens < 4096:
        st.warning("⚠️ Max tokens is below 4096. Test case generation (A5) requires at least 4096 tokens per AC — the value will be raised automatically to 4096 during generation.")
    max_per_ac = st.number_input("Max tests per AC", min_value=6, max_value=15, value=10, step=1,
        help="Maximum test cases kept per acceptance criterion after optimization. Range 6–15.")
    max_test_count = st.number_input("Max test count (global cap)", min_value=10, max_value=2000, value=200, step=10,
        help="Hard global cap across all ACs. Set high enough to not override the per-AC limit (e.g. 200 for 12 ACs × 10 tests).")

    llm_model = api_key = base_url = ""
    use_json_format = True
    ssl_verify = True
    if execution_mode == "online" or reviewer_mode == "online":
        st.subheader("LLM configuration")

        PROVIDER_PRESETS = {
            "GitHub Copilot (VS Code Bridge)": {
                "base_url": "http://127.0.0.1:3100/v1",
                "default_model": "gpt-4o",
                "needs_key": False,
                "json_format": False,
                "note": (
                    "Requires the Copilot LLM Bridge extension to be installed and VS Code running. "
                    "The bridge auto-starts when VS Code opens. "
                    "Model name is matched against available Copilot models (e.g. gpt-4o, claude-sonnet-4-5). "
                    "JSON-format mode is disabled because the bridge instructs Copilot via the system prompt instead."
                ),
            },
            "Ollama (Local)": {
                "base_url": "http://localhost:11434/v1",
                "default_model": "llama3.2",
                "needs_key": False,
                "json_format": True,
                "note": "Run `ollama serve` then `ollama pull <model>` to download a model.",
            },
            "LM Studio (Local)": {
                "base_url": "http://localhost:1234/v1",
                "default_model": "local-model",
                "needs_key": False,
                "json_format": False,
                "note": "Start the local server in LM Studio → Local Server tab.",
            },
            "Groq (Cloud – free tier)": {
                "base_url": "https://api.groq.com/openai/v1",
                "default_model": "llama-3.3-70b-versatile",
                "needs_key": True,
                "json_format": True,
                "note": "Free API key at console.groq.com – no corporate proxy needed for most networks.",
            },
            "Together AI (Cloud – free tier)": {
                "base_url": "https://api.together.xyz/v1",
                "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
                "needs_key": True,
                "json_format": True,
                "note": "Free API key at api.together.ai",
            },
            "OpenAI": {
                "base_url": "https://api.openai.com/v1",
                "default_model": "gpt-4o-mini",
                "needs_key": True,
                "json_format": True,
                "note": "",
            },
            "Company / Azure OpenAI": {
                "base_url": "",
                "default_model": "",
                "needs_key": True,
                "json_format": False,
                "ssl_verify": False,
                "note": (
                    "For company-hosted or Azure OpenAI endpoints. "
                    "Enter your company base URL (e.g. https://api.company.com/v1), "
                    "the exact model/deployment name, and your API key. "
                    "SSL verification is OFF by default (corporate TLS proxy). "
                    "JSON-format mode is OFF by default — many corporate proxies do not support response_format=json_object."
                ),
            },
            "Custom / Other": {
                "base_url": "",
                "default_model": "",
                "needs_key": True,
                "json_format": True,
                "note": "Any OpenAI-compatible endpoint (vLLM, Mistral, Azure OpenAI, etc.).",
            },
        }

        provider = st.selectbox("Provider", list(PROVIDER_PRESETS.keys()), index=0)
        preset = PROVIDER_PRESETS[provider]

        llm_model = st.text_input("Model name", value=preset["default_model"])
        base_url = st.text_input("Base URL", value=preset["base_url"])

        if preset["needs_key"]:
            api_key = st.text_input("API key", type="password")
        else:
            api_key = "local"  # dummy value – local servers ignore the Authorization header
            st.caption("No API key required for local providers.")

        use_json_format = st.checkbox(
            "Use JSON-format mode",
            value=preset["json_format"],
            help="Sends response_format={'type':'json_object'} to the model. Disable for models that do not support it (e.g. some LM Studio setups).",
        )
        ssl_verify = preset.get("ssl_verify", True)
        if preset.get("note"):
            st.caption(preset["note"])

uploaded = st.file_uploader("Upload story / stories / epic input (.txt, .md, .json, .docx)", type=["txt", "md", "json", "docx"])
text_input = st.text_area(
    "Or paste the requirement text",
    height=240,
    help=(
        "Accepts any of these formats:\n"
        "• Standard: `Story: Title` / `User Story: Title` with Acceptance Criteria\n"
        "• Epic + stories: `Epic: Title` followed by `User Story:` blocks\n"
        "• Gherkin/BDD: `Feature:` / `Scenario:` with `Given/When/Then`\n"
        "• Jira-style: `US-123: Title` or `US1:` blocks\n"
        "• Markdown headings: `## Story Name` as story separators\n"
        "• Numbered list: `1. As a user ...`\n"
        "• JSON array: `[{\"title\": \"...\", \"acceptance_criteria\": [...]}]`\n"
        "• Plain text: lines starting with 'must'/'should' used as criteria"
    ),
)

run_clicked = st.button("Generate test assets")

if run_clicked:
    if not uploaded and not text_input.strip():
        st.error("Upload a file or paste requirement text.")
        st.stop()

    if uploaded:
        if uploaded.name.lower().endswith(".docx"):
            from src.utils.io_utils import extract_docx_text
            document_text = extract_docx_text(uploaded.getvalue())
        else:
            document_text = uploaded.getvalue().decode("utf-8", errors="ignore")
    else:
        document_text = text_input
    _progress_bar = st.progress(0, text="Starting pipeline…")
    _status_text = st.empty()

    def _on_progress(done: int, total: int, label: str):
        pct = int(done / total * 100) if total else 100
        _progress_bar.progress(pct, text=label)
        _status_text.empty()

    try:
        result = pipeline.run(
        document_text=document_text,
        output_dir="outputs",
        execution_mode=execution_mode,
        reviewer_mode=reviewer_mode,
        selected_layers=selected_layers,
        selected_test_types=selected_types_combined,
        selected_exec_tags=selected_exec_tags,
        llm_config={
            "model": llm_model,
            "api_key": api_key,
            "base_url": base_url,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "use_json_format": use_json_format,
            "ssl_verify": ssl_verify,
        },
        max_test_count=int(max_test_count),
        max_per_ac=int(max_per_ac),
        progress_callback=_on_progress if execution_mode == "online" else None,
    )
    except Exception as exc:
        st.error(f"Execution failed: {exc}")
        st.stop()

    _progress_bar.progress(100, text="Done!")
    _status_text.empty()
    st.session_state["casegen_result"] = result
    st.session_state["casegen_tc_df"] = result.get("test_cases_df", pd.DataFrame()).fillna("")
    st.session_state["casegen_trace_rows"] = pd.DataFrame(result["traceability"].get("readable", []))
    st.session_state["casegen_reviewer_table"] = pd.DataFrame(result["review_summary"].get("reviewer_table", []))

if "casegen_result" in st.session_state:
    result = st.session_state["casegen_result"]
    tc_df = st.session_state["casegen_tc_df"]
    trace_rows = st.session_state["casegen_trace_rows"]
    reviewer_table = st.session_state["casegen_reviewer_table"]
    domain_analysis = result["manifest"]["domain_analysis"]
    _subdomain = domain_analysis.get('subdomain') or ''
    _subdomain_html = f" &nbsp;&nbsp;|&nbsp;&nbsp; <b>Subdomain:</b> {_subdomain}" if _subdomain else ""

    st.markdown(f"""
    <div class='info-card'>
        <b>ProjectState:</b> {result['manifest'].get('project_state','')} &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>Domain:</b> {domain_analysis.get('primary_domain','')}{_subdomain_html}
    </div>
    """, unsafe_allow_html=True)

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Stories", result["manifest"]["requirements_summary"].get("story_count", 0))
    s2.metric("Acceptance Criteria (AC's)", result["manifest"]["requirements_summary"].get("ac_count", 0))
    s3.metric("Test Cases", len(result["test_cases"]))
    s4.metric("Coverage %", f"{float(result['traceability']['summary'].get('traceability_coverage_percent', 0.0)):.1f}%")

    tabs = st.tabs(["Test Cases", "Traceability", "Dashboard", "Agent Output"])

    with tabs[0]:
        st.subheader("Generated test cases")
        st.caption("Ordered by story and acceptance criterion.")
        st.dataframe(tc_df, use_container_width=True, height=520)
        excel_bytes = Path(result["artifact_dir"]) / "test_cases.xlsx"
        st.download_button("Download test cases Excel", data=excel_bytes.read_bytes(), file_name="test_cases.xlsx")
        st.download_button("Download test cases JSON", data=json.dumps(result["test_cases"], indent=2), file_name="test_cases.json")

    with tabs[1]:
        st.subheader("Traceability")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total ACs", result["traceability"]["summary"].get("total_acs", 0))
        c2.metric("Covered ACs", result["traceability"]["summary"].get("covered_acs", 0))
        c3.metric("Uncovered ACs", result["traceability"]["summary"].get("uncovered_count", 0))
        c4.metric("Coverage %", f"{float(result['traceability']['summary'].get('traceability_coverage_percent', 0.0)):.1f}%")

        st.markdown("---")

        # ── Shared lookups ────────────────────────────────────────────────────
        _tc_lookup = {
            tc["test_case_id"]: tc
            for tc in result["test_cases"]
        }

        _removed_map: dict = {}
        for _mrow in result["traceability"].get("matrix", []):
            _removed_map[_mrow["ac_id"]] = _mrow.get("removed_test_cases", [])

        from collections import defaultdict as _dd
        _story_map: dict = _dd(lambda: {"title": "", "acs": []})
        for _row in result["traceability"].get("matrix", []):
            _sid = _row["story_id"]
            _story_map[_sid]["title"] = _row.get("story_title", _sid)
            _story_map[_sid]["acs"].append(_row)

        # Build story → epic lookup from manifest
        _story_epic: dict[str, str] = {
            s["story_id"]: s.get("epic_title", "")
            for s in result.get("manifest", {}).get("stories", [])
        }
        _global_epic = result.get("manifest", {}).get("epic_title", "")

        def _prio_colour(p: str) -> str:
            return {"P1": "#c0392b", "P2": "#e67e22", "P3": "#2980b9", "P4": "#7f8c8d"}.get(p, "#7f8c8d")

        def _scenario_icon(s: str) -> str:
            return {"Positive": "🟢", "Negative": "🔴", "Edge Case": "🟠",
                    "Exception Handling": "⚠️", "Smoke": "💨"}.get(s, "🧪")

        def _layer_colour(l: str) -> str:
            return {"UI": "#1a6b3c", "API": "#1a4a8a", "Database": "#6b4a1a", "ETL": "#5a1a6b"}.get(l, "#444")

        # ══════════════════════════════════════════════════════════════════════
        # TRACEABILITY MATRIX TABLE
        # ══════════════════════════════════════════════════════════════════════
        st.markdown("""
        <style>
        .rtm-tbl-wrap    { width:100%; font-family:'Segoe UI',sans-serif; font-size:0.88rem; }
        .rtm-tbl-header  { display:grid;
                           grid-template-columns:12% 16% 26% 30% 16%;
                           background:#0e2d54; color:#ffffff; font-weight:700;
                           padding:8px 12px; border-radius:8px 8px 0 0;
                           font-size:0.8rem; letter-spacing:0.04em;
                           text-transform:uppercase; gap:4px; }
        .rtm-story-bar   { background:#1a4a8a; color:#cce0ff; font-weight:700;
                           padding:6px 14px; font-size:0.85rem;
                           border-left:4px solid #5b9ee1; margin-top:3px; }
        /* Checkbox toggle — hidden, drives expand via CSS sibling selector */
        .rtm-toggle      { display:none; }
        .rtm-ac-group    { border-bottom:1px solid #dde8f5; }
        .rtm-data-row    { display:grid;
                           grid-template-columns:12% 16% 26% 30% 16%;
                           align-items:start; gap:4px;
                           padding:8px 12px; background:#f7fbff; }
        .rtm-data-row:hover { background:#f0f5ff; }
        .rtm-toggle:checked ~ .rtm-data-row { background:#dbeafe; }
        .rtm-cell        { overflow:hidden; padding:0 4px; }
        .rtm-epic-cell   { color:#5b6e8a; font-size:0.8rem; padding-top:3px; }
        .rtm-story-cell  { color:#123b73; font-weight:600; font-size:0.82rem; padding-top:3px; }
        .rtm-ac-cell     { color:#222; }
        .rtm-ac-id       { font-weight:700; color:#204c84; margin-right:5px; }
        .rtm-tcmap-cell  { color:#1a4a8a; font-size:0.78rem; line-height:1.7;
                           padding-top:3px; word-break:break-all; }
        .rtm-tc-cnt      { display:flex; flex-direction:column; align-items:center;
                           justify-content:flex-start; padding-top:2px; }
        .rtm-cnt-badge   { display:inline-flex; align-items:center; justify-content:center;
                           background:#204c84; color:#fff; border-radius:20px;
                           padding:3px 14px; font-size:0.82rem; font-weight:700;
                           cursor:pointer; user-select:none; min-width:52px;
                           box-shadow:0 1px 3px rgba(32,76,132,0.25);
                           transition:background 0.15s; }
        .rtm-cnt-badge:hover { background:#1a3d6e; }
        .rtm-toggle:checked ~ .rtm-data-row .rtm-cnt-badge { background:#1a3d6e; }
        .rtm-cnt-zero    { display:inline-flex; align-items:center; justify-content:center;
                           background:#e0e0e0; color:#888; border-radius:20px;
                           padding:3px 14px; font-size:0.82rem; font-weight:700; min-width:52px; }
        .rtm-cnt-hint    { font-size:0.7rem; color:#5b9ee1; margin-top:3px;
                           font-style:italic; text-align:center; }
        .rtm-cnt-hint::before { content:"▶ expand"; }
        .rtm-toggle:checked ~ .rtm-data-row .rtm-cnt-hint::before { content:"▼ collapse"; }
        /* Detail panel — hidden by default, shown when toggle checked */
        .rtm-detail-panel  { display:none; padding:12px 16px 16px 16px;
                             background:#f0f6ff; border-top:1px solid #ccdff5; }
        .rtm-toggle:checked ~ .rtm-detail-panel { display:block; }
        .rtm-detail-hdr  { font-size:0.78rem; font-weight:700; color:#204c84;
                           text-transform:uppercase; letter-spacing:0.05em; margin-bottom:10px; }
        .rtm-tc-cards    { display:flex; flex-wrap:wrap; gap:10px; }
        .rtm-tc-card     { background:#ffffff; border:1px solid #ccdff5;
                           border-radius:8px; padding:10px 14px; min-width:230px;
                           flex:1 1 230px; max-width:360px; }
        .rtm-tc-card-id  { font-weight:700; color:#204c84; font-size:0.88rem; }
        .rtm-tc-card-ttl { color:#222; font-size:0.83rem; margin:4px 0 6px; line-height:1.35; }
        .rtm-tc-meta     { display:flex; flex-wrap:wrap; gap:4px; }
        .rtm-pill        { border-radius:10px; padding:2px 8px; font-size:0.72rem;
                           font-weight:600; white-space:nowrap; }
        .rtm-no-tc       { color:#a33; font-size:0.84rem; padding:4px 0; }
        </style>
        """, unsafe_allow_html=True)

        # ── Table header ──────────────────────────────────────────────────────
        st.markdown(
            '<div class="rtm-tbl-wrap">'
            '<div class="rtm-tbl-header">'
            '<span>Epic</span>'
            '<span>User Story</span>'
            '<span>Acceptance Criteria</span>'
            '<span>TCs Mapped</span>'
            '<span>Test Cases Mapped (Count)</span>'
            '</div>',
            unsafe_allow_html=True,
        )

        # ── Rows per story ────────────────────────────────────────────────────
        for _sid, _sdata in _story_map.items():
            _epic = _story_epic.get(_sid, "") or _global_epic
            _acs  = _sdata["acs"]
            _total_tcs = sum(len(a.get("mapped_test_cases", [])) for a in _acs)

            st.markdown(
                f'<div class="rtm-story-bar">'
                f'📘 &nbsp;{_sid} &nbsp;–&nbsp; {_sdata["title"]} &nbsp;&nbsp;'
                f'<span style="font-weight:400;font-size:0.8rem;">'
                f'({len(_acs)} ACs &nbsp;·&nbsp; {_total_tcs} Test Cases)'
                f'</span></div>',
                unsafe_allow_html=True,
            )

            # One toggle-driven group per AC
            _rows_html = ""
            for _idx_ac, _ac in enumerate(_acs):
                _ac_id   = _ac["ac_id"]
                _ac_txt  = _ac["ac_text"]
                _tc_ids  = _ac.get("mapped_test_cases", [])
                _cnt     = len(_tc_ids)

                # Unique checkbox ID — sanitise ac_id for use as HTML id
                _chk_id  = f"rtm_{_sid}_{_idx_ac}".replace(" ", "_").replace("/", "_").replace(".", "_")

                # TC IDs comma-separated
                _tc_ids_str = (
                    ", ".join(_tc_ids)
                    if _tc_ids
                    else '<span style="color:#bbb;">—</span>'
                )

                # Count badge / zero badge
                if _cnt:
                    _cnt_cell = (
                        f'<div class="rtm-tc-cnt">'
                        f'<label for="{_chk_id}" class="rtm-cnt-badge">🧪 {_cnt}</label>'
                        f'<span class="rtm-cnt-hint"></span>'
                        f'</div>'
                    )
                else:
                    _cnt_cell = '<div class="rtm-tc-cnt"><span class="rtm-cnt-zero">0</span></div>'

                # Detail panel — TC cards
                _detail = '<div class="rtm-detail-panel">'
                if _tc_ids:
                    _detail += (
                        f'<div class="rtm-detail-hdr">'
                        f'🧪 &nbsp;Test Cases &nbsp;'
                        f'<span style="background:#204c84;color:#fff;border-radius:8px;'
                        f'padding:1px 9px;font-size:0.72rem;font-weight:600;">{_cnt}</span>'
                        f'</div>'
                        f'<div class="rtm-tc-cards">'
                    )
                    for _tcid in _tc_ids:
                        _tc  = _tc_lookup.get(_tcid, {})
                        _ttl = _tc.get("title", _tcid)
                        _l   = _tc.get("test_case_layer", "—")
                        _p   = _tc.get("priority", "—")
                        _sc   = _tc.get("scenario_type", "—")
                        _ttype = _tc.get("test_type", "Functional")
                        _pcol = _prio_colour(_p)
                        _lcol = _layer_colour(_l)
                        _icon = _scenario_icon(_sc)
                        _detail += (
                            f'<div class="rtm-tc-card">'
                            f'<div class="rtm-tc-card-id">{_tcid}</div>'
                            f'<div class="rtm-tc-card-ttl">{_ttl}</div>'
                            f'<div class="rtm-tc-meta">'
                            f'<span class="rtm-pill" style="background:{_lcol}22;color:{_lcol};border:1px solid {_lcol}55;">{_l}</span>'
                            f'<span class="rtm-pill" style="background:{_pcol}22;color:{_pcol};border:1px solid {_pcol}55;">{_p}</span>'
                            f'<span class="rtm-pill" style="background:#f0f0f0;color:#444;border:1px solid #ccc;">{_icon} {_sc}</span>'
                            f'<span class="rtm-pill" style="background:#f0f8ff;color:#2c5f8a;border:1px solid #bbd;">{_ttype}</span>'
                            f'</div></div>'
                        )
                    _detail += '</div>'
                else:
                    _detail += '<div class="rtm-no-tc">No test cases mapped to this AC.</div>'
                _detail += '</div>'  # close rtm-detail-panel

                # Group: hidden checkbox → data row → detail panel
                # CSS sibling selectors: .rtm-toggle:checked ~ .rtm-data-row / ~ .rtm-detail-panel
                _rows_html += (
                    f'<div class="rtm-ac-group">'
                    f'<input type="checkbox" id="{_chk_id}" class="rtm-toggle">'
                    f'<div class="rtm-data-row">'
                    f'<div class="rtm-cell rtm-epic-cell">{_epic or "—"}</div>'
                    f'<div class="rtm-cell rtm-story-cell">{_sid}</div>'
                    f'<div class="rtm-cell rtm-ac-cell">'
                    f'<span class="rtm-ac-id">{_ac_id}</span>{_ac_txt}'
                    f'</div>'
                    f'<div class="rtm-cell rtm-tcmap-cell">{_tc_ids_str}</div>'
                    f'<div class="rtm-cell">{_cnt_cell}</div>'
                    f'</div>'
                    f'{_detail}'
                    f'</div>'
                )

            st.markdown(_rows_html, unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)  # close rtm-tbl-wrap


    with tabs[2]:
        import altair as alt
        from collections import Counter as _Counter

        st.subheader("Dashboard")
        summary = result["dashboard"]["summary"]
        verdict = result["dashboard"]["final_verdict"]
        quality_gaps = result["dashboard"]["quality_gaps"]
        trace_sum = result["traceability"]["summary"]

        # ── KPI Row ──────────────────────────────────────────────────────────
        k1, k2, k3 = st.columns(3)
        k1.metric("Total Test Cases", summary["total_tests_after"])
        k2.metric("Coverage %", f"{float(summary['traceability_coverage_percent']):.1f}%")
        _opt_dedup_pct = float(result["dashboard"]["optimization_impact"].get("deduplication_reduction_percent", 0))
        _opt_rank_pct = float(result["dashboard"]["optimization_impact"].get("priority_scoring_reduction_percent", 0))
        k3.metric("Test Optimization %", f"{float(summary['reduction_percent']):.1f}%")
        st.markdown("---")

        # ── Test Optimization: Before vs After bar chart ──────────────────────
        st.markdown("**Test Optimization % — Before vs After**")
        st.markdown(
            f"<div style='font-size:0.92rem; color:#204c84; margin:-6px 0 10px 0;'>"
            f"Deduplication Impact &nbsp;—&nbsp; <b>{_opt_dedup_pct:.1f}%</b> &nbsp;&nbsp;|&nbsp;&nbsp;"
            f"Priority-Based Test Case Capping Impact &nbsp;—&nbsp; <b>{_opt_rank_pct:.1f}%</b>"
            f"</div>",
            unsafe_allow_html=True,
        )
        _before = summary.get("total_tests_before", 0)
        _after  = summary.get("total_tests_after", 0)
        _reduced = max(_before - _after, 0)
        _pct_saved = round(_reduced / max(_before, 1) * 100, 1)
        _pct_after = round(_after / max(_before, 1) * 100, 1)
        _opt_df = pd.DataFrame({
            "Stage": ["Before Optimization", "After Optimization"],
            "Tests": [_before, _after],
            "Label": [
                f"{_before} (100%)",
                f"{_after} ({_pct_after}%)",
            ],
        })
        _opt_bars = (
            alt.Chart(_opt_df)
            .mark_bar(size=70)
            .encode(
                x=alt.X("Stage:N", sort=["Before Optimization", "After Optimization"],
                         axis=alt.Axis(labelAngle=0), title=None),
                y=alt.Y("Tests:Q", title="Number of Tests"),
                color=alt.Color(
                    "Stage:N",
                    scale=alt.Scale(
                        domain=["Before Optimization", "After Optimization"],
                        range=["#d95f02", "#1b9e77"],
                    ),
                    legend=None,
                ),
                tooltip=["Stage:N", "Tests:Q"],
            )
        )
        _opt_line = (
            alt.Chart(_opt_df)
            .mark_line(color="#204c84", strokeWidth=2.5, point=alt.OverlayMarkDef(color="#204c84", size=80))
            .encode(
                x=alt.X("Stage:N", sort=["Before Optimization", "After Optimization"]),
                y=alt.Y("Tests:Q"),
            )
        )
        _opt_labels = _opt_bars.mark_text(dy=-22, fontSize=14, fontWeight="bold", color="#333").encode(
            text="Label:N"
        )
        # Midpoint label on the line: anchored to the Before point, shifted right to sit mid-line
        _mid_y = (_before + _after) / 2
        _mid_label = f"−{_reduced} ({_pct_saved}% optimized)"
        _mid_df = pd.DataFrame({
            "Stage": ["Before Optimization"],
            "y": [_mid_y],
            "label": [_mid_label],
        })
        _opt_mid_text = (
            alt.Chart(_mid_df)
            .mark_text(
                align="center",
                dx=120,          # shift right to sit between the two bars
                fontSize=12,
                fontWeight="bold",
                color="#204c84",
                fontStyle="italic",
                lineBreak="\n",
            )
            .encode(
                x=alt.X("Stage:N", sort=["Before Optimization", "After Optimization"]),
                y=alt.Y("y:Q"),
                text="label:N",
            )
        )
        st.altair_chart(
            (_opt_bars + _opt_line + _opt_labels + _opt_mid_text)
            .properties(height=300),
            use_container_width=True,
        )
        st.markdown("---")

        def _hbar(df: pd.DataFrame, x_col: str, y_col: str, scheme: str, height: int = 180):
            bars = (
                alt.Chart(df)
                .mark_bar(cornerRadiusTopRight=5, cornerRadiusBottomRight=5)
                .encode(
                    x=alt.X(f"{x_col}:Q", title="Count"),
                    y=alt.Y(f"{y_col}:N", sort="-x", title=None),
                    color=alt.Color(f"{y_col}:N", scale=alt.Scale(scheme=scheme), legend=None),
                    tooltip=[f"{y_col}:N", f"{x_col}:Q"],
                )
            )
            labels = bars.mark_text(align="left", dx=4, color="#444").encode(
                text=alt.Text(f"{x_col}:Q")
            )
            return (bars + labels).properties(height=height)

        def _donut(df: pd.DataFrame, theta_col: str, color_col: str, scheme: str, height: int = 240):
            df = df.copy()
            _total = df[theta_col].sum()
            df["_slice_label"] = df.apply(
                lambda r: f"{int(r[theta_col])} ({r[theta_col] / max(_total, 1) * 100:.1f}%)", axis=1
            )
            base = (
                alt.Chart(df)
                .encode(
                    theta=alt.Theta(f"{theta_col}:Q", stack=True),
                    color=alt.Color(
                        f"{color_col}:N",
                        scale=alt.Scale(scheme=scheme),
                        legend=alt.Legend(title=color_col),
                    ),
                    tooltip=[f"{color_col}:N", f"{theta_col}:Q"],
                )
            )
            arc = base.mark_arc(innerRadius=55, outerRadius=100)
            text = base.mark_text(radius=125, fontSize=11, fontWeight="bold", color="#333").encode(
                text=alt.Text("_slice_label:N")
            )
            return (arc + text).properties(height=height)

        # ── Row 1: Priority (donut) + Layer (donut) ───────────────────────────
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Test Cases by Priority**")
            if not tc_df.empty and "Priority" in tc_df.columns:
                p_df = (
                    tc_df["Priority"].value_counts()
                    .reindex(["P1", "P2", "P3", "P4"], fill_value=0)
                    .reset_index()
                )
                p_df.columns = ["Priority", "Count"]
                st.altair_chart(_donut(p_df, "Count", "Priority", "blues"), use_container_width=True)
        with col2:
            st.markdown("**Test Cases by Layer**")
            if not tc_df.empty and "TestCaseLayer" in tc_df.columns:
                l_df = tc_df["TestCaseLayer"].value_counts().reset_index()
                l_df.columns = ["Layer", "Count"]
                st.altair_chart(_donut(l_df, "Count", "Layer", "tableau10"), use_container_width=True)

        # ── Row 2: Test Suite (h-bar) + Scenario Type (h-bar) ────────────────
        col3, col4 = st.columns(2)
        with col3:
            st.markdown("**Test Cases by Test Type**")
            if not tc_df.empty and "TestType" in tc_df.columns:
                s_df = tc_df["TestType"].value_counts().reset_index()
                s_df.columns = ["Type", "Count"]
                st.altair_chart(_hbar(s_df, "Count", "Type", "set2"), use_container_width=True)
        with col4:
            st.markdown("**Test Cases by Scenario Type**")
            if not tc_df.empty and "ScenarioType" in tc_df.columns:
                sc_df = tc_df["ScenarioType"].value_counts().reset_index()
                sc_df.columns = ["Scenario", "Count"]
                st.altair_chart(_hbar(sc_df, "Count", "Scenario", "pastel1"), use_container_width=True)

        # ── Row 3: Priority × Layer heatmap + Execution Tags ─────────────────
        col5, col6 = st.columns(2)
        with col5:
            st.markdown("**Priority Distribution by Layer** *(heatmap)*")
            if not tc_df.empty and "TestCaseLayer" in tc_df.columns and "Priority" in tc_df.columns:
                heat_df = (
                    tc_df.groupby(["TestCaseLayer", "Priority"])
                    .size()
                    .reset_index(name="Count")
                )
                heatmap = alt.Chart(heat_df).mark_rect().encode(
                    x=alt.X("Priority:N", sort=["P1", "P2", "P3", "P4"], title="Priority"),
                    y=alt.Y("TestCaseLayer:N", title="Layer"),
                    color=alt.Color("Count:Q", scale=alt.Scale(scheme="blues"), title="Count"),
                    tooltip=["TestCaseLayer:N", "Priority:N", "Count:Q"],
                )
                heat_text = heatmap.mark_text(baseline="middle", fontWeight="bold").encode(
                    text="Count:Q",
                    color=alt.condition(
                        alt.datum.Count > 4, alt.value("white"), alt.value("#333")
                    ),
                )
                st.altair_chart((heatmap + heat_text).properties(height=180), use_container_width=True)
        with col6:
            st.markdown("**Execution Tags Distribution**")
            if not tc_df.empty and "ExecutionTags" in tc_df.columns:
                tags_flat = []
                for cell in tc_df["ExecutionTags"]:
                    tags_flat.extend(str(cell).split("\n"))
                tag_counts = _Counter(t.strip() for t in tags_flat if t.strip())
                if tag_counts:
                    tag_df = (
                        pd.DataFrame(tag_counts.items(), columns=["Tag", "Count"])
                        .sort_values("Count", ascending=False)
                    )
                    st.altair_chart(_hbar(tag_df, "Count", "Tag", "set3", height=180), use_container_width=True)

        st.markdown("---")
        # ── Traceability & Coverage ───────────────────────────────────────────
        st.markdown("#### Traceability & Coverage")
        tc1, tc2, tc3, tc4 = st.columns(4)
        tc1.metric("Total ACs", trace_sum.get("total_acs", 0))
        tc2.metric("Covered ACs", trace_sum.get("covered_acs", 0))
        tc3.metric("Uncovered ACs", trace_sum.get("uncovered_count", 0))
        tc4.metric("Coverage %", f"{float(trace_sum.get('traceability_coverage_percent', 0.0)):.1f}%")

        matrix_rows = pd.DataFrame(result["traceability"].get("matrix", []))
        if not matrix_rows.empty and "story_id" in matrix_rows.columns and "coverage" in matrix_rows.columns:
            story_cov_df = (
                matrix_rows.groupby("story_id")
                .apply(lambda g: round(g["coverage"].eq("Covered").sum() / max(len(g), 1) * 100, 1))
                .reset_index(name="Coverage %")
            )
            st.markdown("**AC Coverage by Story (%)**")
            cov_chart = (
                alt.Chart(story_cov_df)
                .mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5)
                .encode(
                    x=alt.X("story_id:N", sort="-y", title="Story", axis=alt.Axis(labelAngle=-30)),
                    y=alt.Y("Coverage %:Q", scale=alt.Scale(domain=[0, 100]), title="Coverage %"),
                    color=alt.Color(
                        "Coverage %:Q",
                        scale=alt.Scale(domain=[0, 100], scheme="redyellowgreen"),
                        legend=None,
                    ),
                    tooltip=["story_id:N", "Coverage %:Q"],
                )
                .properties(height=260)
            )
            labels = cov_chart.mark_text(align="center", dy=-10, fontSize=11, fontWeight="bold", color="#444").encode(
                text=alt.Text("Coverage %:Q", format=".1f")
            )
            st.altair_chart((cov_chart + labels), use_container_width=True)

        st.markdown("---")
        # ── Quality Gaps & Recommendations ───────────────────────────────────
        st.markdown("#### Quality Gaps & Recommendations")
        qg1, qg2, qg3 = st.columns(3)
        qg1.metric("ACs Missing Negative Tests", quality_gaps.get("acs_missing_negative", 0))
        qg2.metric("ACs Missing Edge Tests", quality_gaps.get("acs_missing_edge", 0))
        qg3.metric("ACs Without Tests", quality_gaps.get("acs_without_tests", 0))

        st.markdown("**Top Recommendations**")
        for rec in verdict.get("top_recommendations", []):
            st.markdown(f"- {rec}")

        with st.expander("Full dashboard JSON"):
            st.json(result["dashboard"])
        st.download_button("Download dashboard HTML", data=result["dashboard_html"], file_name="dashboard.html")

    with tabs[3]:
        st.subheader("Agent output")
        st.download_button("Download manifest JSON", data=json.dumps(result["manifest"], indent=2), file_name="manifest.json")
        st.download_button("Download traceability JSON", data=json.dumps(result["traceability"], indent=2), file_name="traceability.json")
        st.download_button("Download reviewer summary JSON", data=json.dumps(result["review_summary"], indent=2), file_name="review_summary.json")
        st.download_button("Download dashboard JSON", data=json.dumps(result["dashboard"], indent=2), file_name="dashboard.json")

    run_cfg = result["manifest"].get("run_config", {})
    src = run_cfg.get("generator_source", "offline_rules")
    if run_cfg.get("execution_mode_requested") == "online" and src != "online_llm":
        st.warning("Online was selected, but LLM generation was not used. See run config below for details.")
    elif src == "online_llm":
        st.success("Online LLM generation was used for this run.")

    with st.expander("Run config and execution evidence"):
        st.json(run_cfg)

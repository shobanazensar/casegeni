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
    reviewer_mode = st.selectbox("Reviewer mode", ["offline", "online"], index=0)
    selected_layers = st.multiselect(
        "Test layers",
        ["UI", "API", "Database", "ETL"],
        default=["UI", "API", "Database", "ETL"],
    )
    selected_types = st.multiselect(
        "Primary test suite",
        ["Functional", "Smoke", "EndToEnd"],
        default=["Functional", "Smoke", "EndToEnd"],
        help="Functional: business rules & AC coverage (default). Smoke: post-deploy health checks. EndToEnd: multi-system flow tests.",
    )
    selected_nf_types = st.multiselect(
        "Non-functional types",
        ["Performance", "Security", "Accessibility", "Compatibility"],
        default=["Security"],
        help="Non-functional test cases are generated after functional tests for each AC.",
    )
    selected_exec_tags = st.multiselect(
        "Execution tags",
        ["Regression", "UAT", "Parity", "Migration"],
        default=["Regression"],
        help="Secondary tags applied to tests. Regression = re-run after changes. These are never primary classifications.",
    )
    selected_types_combined = selected_types + selected_nf_types
    temperature = st.number_input("Temperature", min_value=0.0, max_value=1.5, value=0.2, step=0.05)
    max_tokens = st.number_input("Max tokens", min_value=256, max_value=64000, value=1800, step=128)
    max_per_ac = st.number_input("Max tests per AC", min_value=6, max_value=15, value=10, step=1,
        help="Maximum test cases kept per acceptance criterion after optimization. Range 6–15.")
    max_test_count = st.number_input("Max test count (global cap)", min_value=10, max_value=2000, value=200, step=10,
        help="Hard global cap across all ACs. Set high enough to not override the per-AC limit (e.g. 200 for 12 ACs × 10 tests).")

    llm_model = api_key = base_url = ""
    use_json_format = True
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
        llm_config={
            "model": llm_model,
            "api_key": api_key,
            "base_url": base_url,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "use_json_format": use_json_format,
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

    domain_analysis = result["manifest"]["domain_analysis"]
    tc_df = result.get("test_cases_df", pd.DataFrame()).fillna("")
    trace_rows = pd.DataFrame(result["traceability"].get("readable", []))
    reviewer_table = pd.DataFrame(result["review_summary"].get("reviewer_table", []))

    st.markdown(f"""
    <div class='info-card'>
        <b>ProjectState:</b> {result['manifest'].get('project_state','')} &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>StateDrivenFocus:</b> {result['manifest'].get('state_driven_focus','')} &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>Domain:</b> {domain_analysis.get('primary_domain','')} &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>ApplicationOrProduct:</b> {domain_analysis.get('application_or_product','')} &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>ProductType:</b> {', '.join(domain_analysis.get('module_or_submodules', []))}
    </div>
    """, unsafe_allow_html=True)

    run_cfg = result["manifest"].get("run_config", {})
    src = run_cfg.get("generator_source", "offline_rules")
    if run_cfg.get("execution_mode_requested") == "online" and src != "online_llm":
        st.warning("Online was selected, but LLM generation was not used. See run config below for details.")
    elif src == "online_llm":
        st.success("Online LLM generation was used for this run.")

    with st.expander("Run config and execution evidence"):
        st.json(run_cfg)

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Test Cases", len(result["test_cases"]))
    s2.metric("Stories", result["manifest"]["requirements_summary"].get("story_count", 0))
    s3.metric("Acceptance Criteria", result["manifest"]["requirements_summary"].get("ac_count", 0))
    s4.metric("Coverage %", result["traceability"]["summary"].get("traceability_coverage_percent", 0.0))

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
        c4.metric("Coverage %", f"{result['traceability']['summary'].get('traceability_coverage_percent', 0.0)}%")

        if not trace_rows.empty:
            # Column display config: rename to human-friendly headers and control widths
            col_cfg = {
                "storyId":           st.column_config.TextColumn("Story ID",        width="small"),
                "acId":              st.column_config.TextColumn("AC ID",           width="small"),
                "acText":            st.column_config.TextColumn("AC Summary",      width="large"),
                "testCaseId":        st.column_config.TextColumn("Test Case ID",    width="small"),
                "title":             st.column_config.TextColumn("Title",           width="large"),
                "testCaseLayer":     st.column_config.TextColumn("Layer",           width="small"),
                "scenarioType":      st.column_config.TextColumn("Scenario Type",   width="small"),
                "testSuite":         st.column_config.TextColumn("Test Suite",      width="small"),
                "nonFunctionalType": st.column_config.TextColumn("NF Type",         width="small"),
                "priority":          st.column_config.TextColumn("Priority",        width="small"),
                "automatable":       st.column_config.TextColumn("Automatable",     width="small"),
                "coverage":          st.column_config.TextColumn("Coverage",        width="small"),
                "gapNotes":          st.column_config.TextColumn("Gap Notes",       width="medium"),
            }
            st.dataframe(trace_rows, use_container_width=True, height=520, column_config=col_cfg)
        else:
            st.info("No traceability data available.")

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
        k2.metric("Coverage %", f"{summary['traceability_coverage_percent']}%")
        k3.metric("Tests Reduced", f"{summary['reduction_percent']}%")
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
            return (
                alt.Chart(df)
                .mark_arc(innerRadius=55, outerRadius=100)
                .encode(
                    theta=alt.Theta(f"{theta_col}:Q"),
                    color=alt.Color(
                        f"{color_col}:N",
                        scale=alt.Scale(scheme=scheme),
                        legend=alt.Legend(title=color_col),
                    ),
                    tooltip=[f"{color_col}:N", f"{theta_col}:Q"],
                )
                .properties(height=height)
            )

        # ── Row 1: Priority (donut) + Layer (donut) ───────────────────────────
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Test Cases by Priority**")
            if not tc_df.empty and "priority" in tc_df.columns:
                p_df = (
                    tc_df["priority"].value_counts()
                    .reindex(["P1", "P2", "P3", "P4"], fill_value=0)
                    .reset_index()
                )
                p_df.columns = ["Priority", "Count"]
                st.altair_chart(_donut(p_df, "Count", "Priority", "blues"), use_container_width=True)
        with col2:
            st.markdown("**Test Cases by Layer**")
            if not tc_df.empty and "testCaseLayer" in tc_df.columns:
                l_df = tc_df["testCaseLayer"].value_counts().reset_index()
                l_df.columns = ["Layer", "Count"]
                st.altair_chart(_donut(l_df, "Count", "Layer", "tableau10"), use_container_width=True)

        # ── Row 2: Test Suite (h-bar) + Scenario Type (h-bar) ────────────────
        col3, col4 = st.columns(2)
        with col3:
            st.markdown("**Test Cases by Test Suite / Type**")
            if not tc_df.empty and "testSuite" in tc_df.columns:
                s_df = tc_df["testSuite"].value_counts().reset_index()
                s_df.columns = ["Suite", "Count"]
                st.altair_chart(_hbar(s_df, "Count", "Suite", "set2"), use_container_width=True)
        with col4:
            st.markdown("**Test Cases by Scenario Type**")
            if not tc_df.empty and "scenarioType" in tc_df.columns:
                sc_df = tc_df["scenarioType"].value_counts().reset_index()
                sc_df.columns = ["Scenario", "Count"]
                st.altair_chart(_hbar(sc_df, "Count", "Scenario", "pastel1"), use_container_width=True)

        # ── Row 3: Priority × Layer heatmap + Execution Tags ─────────────────
        col5, col6 = st.columns(2)
        with col5:
            st.markdown("**Priority Distribution by Layer** *(heatmap)*")
            if not tc_df.empty and "testCaseLayer" in tc_df.columns and "priority" in tc_df.columns:
                heat_df = (
                    tc_df.groupby(["testCaseLayer", "priority"])
                    .size()
                    .reset_index(name="Count")
                )
                heatmap = alt.Chart(heat_df).mark_rect().encode(
                    x=alt.X("priority:N", sort=["P1", "P2", "P3", "P4"], title="Priority"),
                    y=alt.Y("testCaseLayer:N", title="Layer"),
                    color=alt.Color("Count:Q", scale=alt.Scale(scheme="blues"), title="Count"),
                    tooltip=["testCaseLayer:N", "priority:N", "Count:Q"],
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
            if not tc_df.empty and "executionTags" in tc_df.columns:
                tags_flat = []
                for cell in tc_df["executionTags"]:
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
        tc4.metric("Coverage %", f"{trace_sum.get('traceability_coverage_percent', 0.0)}%")

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
                .mark_bar(cornerRadiusTopRight=5, cornerRadiusBottomRight=5)
                .encode(
                    x=alt.X("Coverage %:Q", scale=alt.Scale(domain=[0, 100])),
                    y=alt.Y("story_id:N", sort="-x", title=None),
                    color=alt.Color(
                        "Coverage %:Q",
                        scale=alt.Scale(domain=[0, 100], scheme="redyellowgreen"),
                        legend=None,
                    ),
                    tooltip=["story_id:N", "Coverage %:Q"],
                )
                .properties(height=max(60, len(story_cov_df) * 32))
            )
            labels = cov_chart.mark_text(align="left", dx=4, color="#444").encode(
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

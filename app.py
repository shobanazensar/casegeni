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
    selected_layers = st.multiselect("Test layers", ["UI", "API", "Database", "ETL Integration", "E2E"], default=["UI", "API", "Database", "ETL Integration", "E2E"])
    selected_types = st.multiselect("Test types", ["Functional", "Smoke", "Sanity", "Regression", "Performance", "Security", "Accessibility", "Compatibility"], default=["Functional", "Smoke", "Sanity", "Regression", "Performance", "Security", "Accessibility"])
    temperature = st.number_input("Temperature", min_value=0.0, max_value=1.5, value=0.2, step=0.05)
    max_tokens = st.number_input("Max tokens", min_value=256, max_value=64000, value=1800, step=128)
    max_test_count = st.number_input("Max test count", min_value=10, max_value=1000, value=60, step=5)

    llm_model = api_key = base_url = ""
    use_json_format = True
    if execution_mode == "online" or reviewer_mode == "online":
        st.subheader("LLM configuration")

        PROVIDER_PRESETS = {
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
        if preset["note"]:
            st.caption(preset["note"])

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

uploaded = st.file_uploader("Upload story / stories / epic input (.txt, .md, .json)", type=["txt", "md", "json"])
text_input = st.text_area("Or paste the requirement text", height=240)

run_clicked = st.button("Generate test assets")

if run_clicked:
    if not uploaded and not text_input.strip():
        st.error("Upload a file or paste requirement text.")
        st.stop()

    document_text = uploaded.getvalue().decode("utf-8", errors="ignore") if uploaded else text_input
    try:
        result = pipeline.run(
        document_text=document_text,
        output_dir="outputs",
        execution_mode=execution_mode,
        reviewer_mode=reviewer_mode,
        selected_layers=selected_layers,
        selected_test_types=selected_types,
        llm_config={
            "model": llm_model,
            "api_key": api_key,
            "base_url": base_url,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "use_json_format": use_json_format,
        },
        max_test_count=int(max_test_count),
    )
    except Exception as exc:
        st.error(f"Execution failed: {exc}")
        st.stop()

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

    tabs = st.tabs(["Test Cases", "Traceability", "Reviewer", "Dashboard", "Agent Output"])

    with tabs[0]:
        st.subheader("Generated test cases")
        st.caption("Ordered by story and acceptance criterion.")
        st.dataframe(tc_df, use_container_width=True, height=520)
        excel_bytes = Path(result["artifact_dir"]) / "test_cases.xlsx"
        st.download_button("Download test cases Excel", data=excel_bytes.read_bytes(), file_name="test_cases.xlsx")
        st.download_button("Download test cases JSON", data=json.dumps(result["test_cases"], indent=2), file_name="test_cases.json")

    with tabs[1]:
        st.subheader("Traceability")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total ACs", result["traceability"]["summary"].get("total_acs", 0))
        c2.metric("Covered ACs", result["traceability"]["summary"].get("covered_acs", 0))
        c3.metric("Coverage %", result["traceability"]["summary"].get("traceability_coverage_percent", 0.0))
        st.dataframe(trace_rows, use_container_width=True, height=420)

    with tabs[2]:
        st.subheader("Reviewer")
        r1, r2, r3 = st.columns(3)
        r1.metric("Average Score", result["review_summary"].get("avg_reviewer_score", 0.0))
        r2.metric("Needs Human Review", len(result["review_summary"].get("tests_needing_human_review", [])))
        r3.metric("Coverage %", result["review_summary"].get("traceability_coverage_percent", 0.0))
        col1, col2 = st.columns(2)
        col1.markdown("**Scores by Layer**")
        col1.dataframe(pd.DataFrame([{"layer": k, "score": v} for k, v in result["review_summary"].get("scores_by_layer", {}).items()]), use_container_width=True)
        col2.markdown("**Scores by Profile**")
        col2.dataframe(pd.DataFrame([{"profile": k, "score": v} for k, v in result["review_summary"].get("scores_by_profile", {}).items()]), use_container_width=True)
        st.markdown("**Dimension Summary by Profile**")
        st.dataframe(pd.DataFrame([
            {"profile": profile, **scores} for profile, scores in result["review_summary"].get("profile_dimension_summary", {}).items()
        ]), use_container_width=True)
        if result["review_summary"].get("major_common_issues"):
            st.markdown("**Common Issues**")
            for item in result["review_summary"].get("major_common_issues", []):
                st.write(f"- {item}")
        st.markdown("**Detailed Reviewer Output**")
        st.dataframe(reviewer_table, use_container_width=True, height=420)
        with st.expander("Raw reviewer JSON"):
            st.json(result["review_summary"])

    with tabs[3]:
        st.subheader("Dashboard")
        c1, c2, c3, c4 = st.columns(4)
        summary = result["dashboard"]["summary"]
        c1.metric("Tests after optimization", summary["total_tests_after"])
        c2.metric("Coverage %", summary["traceability_coverage_percent"])
        c3.metric("Reviewer score", summary["avg_reviewer_score"])
        c4.metric("Automation readiness %", summary["automation_readiness_percent"])
        st.json(result["dashboard"])
        st.download_button("Download dashboard HTML", data=result["dashboard_html"], file_name="dashboard.html")

    with tabs[4]:
        st.subheader("Agent output")
        st.download_button("Download manifest JSON", data=json.dumps(result["manifest"], indent=2), file_name="manifest.json")
        st.download_button("Download traceability JSON", data=json.dumps(result["traceability"], indent=2), file_name="traceability.json")
        st.download_button("Download reviewer summary JSON", data=json.dumps(result["review_summary"], indent=2), file_name="review_summary.json")
        st.download_button("Download dashboard JSON", data=json.dumps(result["dashboard"], indent=2), file_name="dashboard.json")

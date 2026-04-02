from __future__ import annotations
import argparse
from pathlib import Path
from src.pipeline import TestCasePipeline
from src.utils.io_utils import read_text


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Enterprise Test Case Generation Agent")
    p.add_argument("--input", required=True, help="Path to story/epic input file (.txt/.md/.json)")
    p.add_argument("--output-dir", required=True, help="Directory for generated outputs")
    p.add_argument("--execution-mode", choices=["offline", "online"], default="offline")
    p.add_argument("--reviewer-mode", choices=["offline", "online"], default="offline")
    p.add_argument("--layers", nargs="+", default=["UI", "API", "Database", "ETL Integration", "E2E"])
    p.add_argument("--test-types", nargs="+", default=["Functional", "Smoke", "Sanity", "Regression", "Performance", "Security", "Accessibility", "Compatibility"])
    p.add_argument("--model", default="")
    p.add_argument("--api-key", default="")
    p.add_argument("--base-url", default="")
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--max-tokens", type=int, default=1800)
    p.add_argument("--max-test-count", type=int, default=350)
    return p


def main() -> None:
    args = build_parser().parse_args()
    pipeline = TestCasePipeline(base_dir=Path(__file__).resolve().parent)
    document_text = read_text(args.input)
    result = pipeline.run(
        document_text=document_text,
        output_dir=args.output_dir,
        execution_mode=args.execution_mode,
        reviewer_mode=args.reviewer_mode,
        selected_layers=args.layers,
        selected_test_types=args.test_types,
        llm_config={
            "model": args.model,
            "api_key": args.api_key,
            "base_url": args.base_url,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
        },
        max_test_count=args.max_test_count,
    )
    print(f"Completed. Outputs at: {result['artifact_dir']}")


if __name__ == "__main__":
    main()

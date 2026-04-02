from __future__ import annotations
from pathlib import Path
from datetime import datetime
from src.utils.io_utils import ensure_dir


class A0Orchestrator:
    def execute(
        self,
        document_text: str,
        output_dir: str,
        execution_mode: str,
        reviewer_mode: str,
        selected_layers: list[str],
        selected_test_types: list[str],
        llm_config: dict,
        max_test_count: int,
    ) -> dict:
        artifact_dir = ensure_dir(Path(output_dir) / datetime.now().strftime("%Y%m%d_%H%M%S"))
        return {
            "document_text": document_text,
            "execution_mode": execution_mode,
            "reviewer_mode": reviewer_mode,
            "selected_layers": selected_layers,
            "selected_test_types": selected_test_types,
            "llm_config": llm_config,
            "artifact_dir": str(artifact_dir),
            "max_test_count": max_test_count,
            "artifact_registry": {},
        }

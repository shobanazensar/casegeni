from __future__ import annotations
import json
from pathlib import Path
from src.utils.io_utils import load_json


class AgentBase:
    def __init__(self, base_dir: Path, config_filename: str):
        self.base_dir = Path(base_dir)
        self.config = load_json(self.base_dir / "config" / "agents" / config_filename)

from __future__ import annotations
import json
from pathlib import Path
from typing import Any
import yaml


def extract_docx_text(file_bytes: bytes) -> str:
    """
    Extract plain text from a .docx binary payload.
    Each paragraph becomes one line; blank paragraphs become blank lines.
    """
    import io
    import docx  # python-docx
    doc = docx.Document(io.BytesIO(file_bytes))
    return "\n".join(para.text for para in doc.paragraphs)


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def read_text(path: str | Path) -> str:
    p = Path(path)
    if p.suffix.lower() == ".json":
        return json.dumps(json.loads(p.read_text(encoding="utf-8")), indent=2)
    return p.read_text(encoding="utf-8")


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_yaml(path: str | Path) -> Any:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def dump_json(path: str | Path, payload: Any) -> None:
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

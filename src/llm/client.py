from __future__ import annotations
import json
import re
from urllib import request, error
from typing import Any


class LLMClient:
    def __init__(self, model: str, api_key: str, base_url: str, temperature: float = 0.2, max_tokens: int = 1800, timeout: int = 120, use_json_format: bool = True):
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        # Some local models (Ollama, LM Studio) may not support the
        # response_format={"type":"json_object"} parameter. Set this to
        # False for those providers; the client will then rely on prompt
        # instructions + the built-in JSON extractor instead.
        self.use_json_format = use_json_format

    def is_configured(self) -> bool:
        # api_key is optional for local providers (Ollama, LM Studio).
        # A placeholder value such as "ollama" or "local" is accepted.
        return bool(self.model and self.base_url)

    def _extract_text_content(self, raw: dict) -> tuple[str, str]:
        try:
            choice = raw["choices"][0]
            message = choice["message"]
            content = message.get("content", "")
            finish_reason = choice.get("finish_reason", "") or ""
        except Exception as exc:
            raise ValueError(f"Unexpected LLM response format: {raw}") from exc
        if isinstance(content, str):
            return content, finish_reason
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") in {"text", "output_text"}:
                    parts.append(item.get("text", ""))
                else:
                    parts.append(str(item))
            return "".join(parts), finish_reason
        if isinstance(content, (dict, list)):
            return json.dumps(content, ensure_ascii=False), finish_reason
        return str(content), finish_reason

    def _strip_code_fences(self, text: str) -> str:
        text = (text or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        return text.strip()

    def _extract_balanced_json(self, text: str) -> str:
        text = self._strip_code_fences(text)
        if not text:
            return text
        if text[0] in '{[':
            try:
                json.loads(text)
                return text
            except Exception:
                return text
        starts = [i for i, ch in enumerate(text) if ch in '{[']
        for start in starts:
            stack = []
            in_string = False
            escape = False
            for i in range(start, len(text)):
                ch = text[i]
                if in_string:
                    if escape:
                        escape = False
                    elif ch == '\\':
                        escape = True
                    elif ch == '"':
                        in_string = False
                    continue
                if ch == '"':
                    in_string = True
                elif ch in '{[':
                    stack.append(ch)
                elif ch in '}]':
                    if not stack:
                        break
                    open_ch = stack.pop()
                    if (open_ch, ch) not in {('{', '}'), ('[', ']')}:
                        break
                    if not stack:
                        candidate = text[start:i + 1]
                        try:
                            json.loads(candidate)
                            return candidate
                        except Exception:
                            break
        return text

    def generate_json(self, system_prompt: str, user_prompt: str) -> Any:
        if not self.is_configured():
            raise ValueError("LLM is not configured.")
        # When use_json_format is False (e.g. Ollama/LM Studio without
        # native JSON-mode support) we skip the response_format key and
        # instead reinforce JSON output via the system prompt.
        effective_system = system_prompt
        if not self.use_json_format:
            if "json" not in system_prompt.lower():
                effective_system = system_prompt + "\n\nIMPORTANT: Your entire response must be valid JSON only, with no markdown fences or extra text."
        payload: dict = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": effective_system},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self.use_json_format:
            payload["response_format"] = {"type": "json_object"}
        req = request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"LLM HTTP error {exc.code}: {body[:800]}") from exc
        except Exception as exc:
            raise RuntimeError(f"LLM request failed: {exc}") from exc

        content, finish_reason = self._extract_text_content(raw)
        json_text = self._extract_balanced_json(content)
        try:
            return json.loads(json_text)
        except Exception as exc:
            hint = ""
            if finish_reason == "length":
                hint = " Output appears truncated. Increase max tokens or reduce batch size."
            elif json_text and json_text.lstrip().startswith(("{", "[")):
                hint = " Response looks like partial JSON. Reduce batch size or increase max tokens."
            raise ValueError(f"LLM returned non-JSON content: {json_text[:800]}.{hint}") from exc

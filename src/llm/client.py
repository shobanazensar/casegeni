from __future__ import annotations
import json
import re
import ssl
import time
from urllib import request, error
from typing import Any

# HTTP status codes that indicate a transient server-side problem and are safe to retry.
# 400 (bad request / config error), 401 (auth), 403 (forbidden) are NOT retried —
# they represent permanent caller mistakes that a retry cannot fix.
_RETRYABLE_HTTP_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
_MAX_RETRIES: int = 1       # 1 retry (2 total attempts); delay: 1s
_RETRY_BASE_DELAY: float = 1.0  # seconds; doubles each attempt: 1s → 2s → …


class LLMClient:
    def __init__(self, model: str, api_key: str, base_url: str, temperature: float = 0.2, max_tokens: int = 1800, timeout: int = 120, use_json_format: bool = True, ssl_verify: bool = True):
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        # Optional callback invoked before each retry sleep.
        # Signature: on_retry(attempt: int, error_message: str) -> None
        # Set by callers (A4/A5) to surface retry notices to the UI.
        self.on_retry: object = None  # Callable[[int, str], None] | None
        # Some local models (Ollama, LM Studio) may not support the
        # response_format={"type":"json_object"} parameter. Set this to
        # False for those providers; the client will then rely on prompt
        # instructions + the built-in JSON extractor instead.
        self.use_json_format = use_json_format
        # Set to False to bypass SSL certificate verification.
        # Required in corporate environments that use a custom CA / TLS proxy.
        self.ssl_verify = ssl_verify

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
        ssl_ctx = None if self.ssl_verify else ssl.create_default_context()
        if ssl_ctx is not None:
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        def _do_request(p: dict):
            r = request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(p).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            with request.urlopen(r, timeout=self.timeout, context=ssl_ctx) as resp:
                return json.loads(resp.read().decode("utf-8"))

        # ── Retry loop with exponential backoff ───────────────────────────────
        # Retries on transient server errors (429, 5xx) and network failures only.
        # Permanent errors (400, 401, 403) raise immediately — retrying won't help.
        last_exc: Exception | None = None
        raw: Any = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                raw = _do_request(payload)
                last_exc = None
                break  # success
            except error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="ignore")
                # Newer models (gpt-5.x, o1, o3) require max_completion_tokens instead of
                # max_tokens. Detect this specific 400 and correct the param name once.
                if exc.code == 400 and "max_tokens" in body and "max_completion_tokens" in body:
                    payload.pop("max_tokens", None)
                    payload["max_completion_tokens"] = self.max_tokens
                    try:
                        raw = _do_request(payload)
                        last_exc = None
                        break
                    except error.HTTPError as exc2:
                        body2 = exc2.read().decode("utf-8", errors="ignore")
                        raise RuntimeError(f"LLM HTTP error {exc2.code}: {body2[:800]}") from exc2
                    except Exception as exc2:
                        raise RuntimeError(f"LLM request failed: {exc2}") from exc2
                last_exc = RuntimeError(f"LLM HTTP error {exc.code}: {body[:800]}")
                if exc.code not in _RETRYABLE_HTTP_CODES or attempt >= _MAX_RETRIES:
                    raise last_exc from exc
                if callable(self.on_retry):
                    self.on_retry(attempt + 1, str(last_exc))
                time.sleep(_RETRY_BASE_DELAY * (2 ** attempt))
            except Exception as exc:
                last_exc = RuntimeError(f"LLM request failed: {exc}")
                if attempt >= _MAX_RETRIES:
                    raise last_exc from exc
                if callable(self.on_retry):
                    self.on_retry(attempt + 1, str(last_exc))
                time.sleep(_RETRY_BASE_DELAY * (2 ** attempt))
        if last_exc is not None:
            raise last_exc

        # ── Parse response — inside retry scope so transient empty/garbled
        # responses are retried; token-limit truncations fail immediately. ─────
        content, finish_reason = self._extract_text_content(raw)

        # Token-limit truncation is a permanent config error — retrying with
        # identical params will produce the same truncated output every time.
        if finish_reason == "length":
            raise RuntimeError(
                f"LLM response was truncated (finish_reason=length). "
                f"The current max_tokens setting ({self.max_tokens}) is too low for this request. "
                f"Increase max_tokens in the LLM configuration and retry."
            )

        json_text = self._extract_balanced_json(content)
        try:
            return json.loads(json_text)
        except Exception as exc:
            hint = ""
            if json_text and json_text.lstrip().startswith(("{", "[")):
                hint = " Response looks like partial JSON — reduce batch size or increase max_tokens."
            raise ValueError(f"LLM returned non-JSON content: {json_text[:400]}.{hint}") from exc

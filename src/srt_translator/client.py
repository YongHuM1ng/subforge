import asyncio
import json
import sys
import time
from typing import Any

import aiohttp

from common.net import resolve_proxy

TRANSLATION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"translations": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
        "required": ["id", "text"]
    }}},
    "required": ["translations"]
}

ANALYSIS_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"}, "style": {"type": "string"},
        "corrections": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "id": {"type": "string"}, "span": {"type": "string"},
                "type": {"type": "string", "enum": ["asr", "ocr", "ruby", "punctuation", "segmentation", "term"]},
                "original": {"type": "string"}, "corrected": {"type": "string"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                "reason": {"type": "string"}
            },
            "required": ["id", "span", "type", "original", "corrected", "confidence", "reason"]
        }},
        "terms": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"source": {"type": "string"}, "target": {"type": "string"}, "note": {"type": "string"}},
            "required": ["source", "target", "note"]
        }}
    },
    "required": ["summary", "style", "corrections", "terms"]
}


class LLMHTTPError(RuntimeError):
    def __init__(self, status: int, body: str, retryable: bool | None = None):
        super().__init__(f"HTTP {status}: {body[:500]}")
        self.status = status
        self.retryable = retryable


class ContentFilteredError(RuntimeError):
    """模型因内容审查/拒答没有返回可用内容。"""

    def __init__(self, message: str, status: int = 200, model: str | None = None):
        super().__init__(message)
        self.status = status
        self.model = model


MODERATION_MARKERS = (
    "moderation", "content policy", "content_policy", "content filter", "content_filter",
    "content management", "safety", "flagged", "refusal", "refuse", "blocked",
    "prohibited", "inappropriate", "unsafe", "violat", "sensitive",
    "policy violation", "usage policy", "harmful",
    "审查", "审核", "敏感", "违规", "拒绝", "安全策略", "内容政策",
)


STRUCTURED_OUTPUT_MARKERS = (
    "response_format", "json_schema", "json_object", "structured output", "structured_output",
    "structured outputs",
)


def _brief(text: str, limit: int = 300) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:limit] + "…"


def looks_like_moderation(status: int, body: str) -> bool:
    """HTTP 400/403 是否像内容审查/拒答，而不是参数或权限错误。"""
    if status not in (400, 403):
        return False
    low = (body or "").lower()
    if any(marker in low for marker in MODERATION_MARKERS):
        return True
    try:
        data = json.loads(body)
    except (TypeError, json.JSONDecodeError):
        return False
    error = data.get("error") if isinstance(data, dict) else None
    if not isinstance(error, dict):
        return False
    text = f"{error.get('code') or ''} {error.get('type') or ''}".lower()
    return any(marker in text for marker in MODERATION_MARKERS)


class LLMClient:
    def __init__(self, endpoint: str, api_key: str, model: str, timeout: int = 120, retries: int = 3,
                 structured_output: str = "json_schema", debug: bool = False, proxy: str = "system"):
        self.endpoint, self.api_key, self.model = endpoint, api_key, model
        self.timeout, self.retries, self.structured_output, self.debug = timeout, retries, structured_output, debug
        self.proxy = resolve_proxy(endpoint, proxy)
        self._session: aiohttp.ClientSession | None = None
        self.usage: dict[str, float] = {}
        if self.proxy:
            label = "系统代理" if (proxy or "").strip().lower() == "system" else "指定代理"
            print(f"[代理] 已启用{label}：{self.proxy}", file=sys.stderr, flush=True)
        elif self.debug:
            print("[代理] 未使用代理，直连", file=sys.stderr, flush=True)

    async def _get_session(self) -> aiohttp.ClientSession:
        """复用同一个连接池，避免每次请求都重新握手。"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit=32, ttl_dns_cache=300),
                timeout=aiohttp.ClientTimeout(total=self.timeout, connect=30, sock_read=self.timeout),
            )
        return self._session

    async def aclose(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    def _should_retry_http_error(self, error: LLMHTTPError) -> bool:
        # Retry rate limits, timeouts, connection handoff errors, and server-side
        # failures. Client errors such as 401/403/404/400 are normally permanent
        # and should be reported immediately instead of wasting API quota.
        if error.retryable is not None:
            return error.retryable
        return error.status in (408, 409, 425, 429) or 500 <= error.status <= 599

    @staticmethod
    def _retry_after(response: aiohttp.ClientResponse) -> float | None:
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            return None

    async def _sleep_before_retry(self, attempt: int, retry_after: float | None = None) -> None:
        # Exponential backoff, with Retry-After taking precedence when supplied.
        # Cap it so a server asking for a one-hour wait does not hang the CLI.
        delay = retry_after if retry_after is not None else min(60.0, 2 ** attempt)
        if delay > 120.0:
            print(f"[API] Retry-After={delay:.0f}s 过长，最多等待 120s", file=sys.stderr, flush=True)
            delay = 120.0
        if self.debug:
            print(f"[API] retrying in {delay:.1f}s", file=sys.stderr, flush=True)
        await asyncio.sleep(delay)

    def _build_body(self, system: str, user: str, schema: dict[str, Any] | None,
                    mode: str, model: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if mode == "json_schema" and schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "subtitle_response", "strict": True, "schema": schema}}
        elif mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        return body

    def _accumulate_usage(self, usage: Any) -> None:
        if not isinstance(usage, dict):
            return
        for key, value in usage.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                self.usage[key] = self.usage.get(key, 0.0) + float(value)

    def usage_summary(self) -> str:
        if not self.usage:
            return ""
        parts = []
        for key, label in (("prompt_tokens", "输入"), ("completion_tokens", "输出"), ("total_tokens", "合计")):
            if key in self.usage:
                parts.append(f"{label} {int(self.usage[key]):,} tokens")
        cost = self.usage.get("cost") or self.usage.get("total_cost")
        if cost:
            parts.append(f"费用 ${cost:.4f}")
        return " · ".join(parts)

    async def chat_json(self, system: str, user: str, schema: dict[str, Any] | None = None,
                        label: str = "request", model: str | None = None) -> str:
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        timeout = aiohttp.ClientTimeout(total=self.timeout, connect=30, sock_read=self.timeout)
        last_error: Exception | None = None
        mode = self.structured_output
        attempt = 0
        while attempt <= self.retries:
            body = self._build_body(system, user, schema, mode, model)
            started = time.monotonic()
            if self.debug:
                print(
                    f"[API] {label} attempt {attempt + 1}/{self.retries + 1} -> {self.endpoint} "
                    f"| input={len(user)} chars | format={mode}",
                    file=sys.stderr, flush=True,
                )
            try:
                session = await self._get_session()
                async with session.post(
                    self.endpoint, json=body, headers=headers,
                    proxy=self.proxy, timeout=timeout,
                ) as response:
                    response_text = await response.text()
                    if response.status >= 400:
                        if looks_like_moderation(response.status, response_text):
                            raise ContentFilteredError(
                                f"HTTP {response.status} 内容审查/拒答：{_brief(response_text)}",
                                status=response.status, model=model or self.model,
                            )
                        error = LLMHTTPError(response.status, response_text)
                        error.retry_after = self._retry_after(response)
                        # 不做自动降级：明确告诉用户需要手动改配置，避免静默改变请求。
                        if response.status == 400 and "response_format" in body:
                            # 只认明确指向结构化输出参数的报错；"invalid" 之类的泛词会把
                            # 模型名错误、上下文超长等 400 误报成 structured_output 问题。
                            low = response_text.lower()
                            if any(word in low for word in STRUCTURED_OUTPUT_MARKERS):
                                raise LLMHTTPError(
                                    response.status,
                                    f"接口不接受 structured_output={mode}；"
                                    "请把 config.toml 的 [api] structured_output 改为 "
                                    "json_object 或 none 后重试",
                                    retryable=False,
                                )
                        raise error
                    data = json.loads(response_text)
                    choices = data.get("choices") or []
                    if not choices:
                        message = data.get("error") or data.get("message") or data
                        raise ContentFilteredError(
                            f"API 返回空 choices（completion=0）：{_brief(message)}；"
                            "可能是上游内容审查/模型拒绝或代理异常。",
                            status=response.status, model=model or self.model,
                        )
                    choice = choices[0] if isinstance(choices[0], dict) else {}
                    if str(choice.get("finish_reason") or "").lower() == "content_filter":
                        raise ContentFilteredError(
                            "模型触发内容审查（finish_reason=content_filter）",
                            status=response.status, model=model or self.model,
                        )
                    message_obj = choice.get("message") if isinstance(choice.get("message"), dict) else {}
                    refusal = message_obj.get("refusal")
                    if isinstance(refusal, str) and refusal.strip():
                        raise ContentFilteredError(
                            f"模型拒绝生成：{_brief(refusal)}",
                            status=response.status, model=model or self.model,
                        )
                    content = message_obj.get("content")
                    if not isinstance(content, str) or not content.strip():
                        raise LLMHTTPError(response.status, f"API 返回空 content：{data}", retryable=True)
                    self._accumulate_usage(data.get("usage"))
                    if self.debug:
                        elapsed = time.monotonic() - started
                        print(
                            f"[API] {label} HTTP {response.status} in {elapsed:.1f}s "
                            f"| output={len(content)} chars | usage={data.get('usage', {})}",
                            file=sys.stderr, flush=True,
                        )
                    return content
            except ContentFilteredError:
                # 审查/拒答由批次层负责重试和回退，不当作网络错误重复请求。
                raise
            except LLMHTTPError as exc:
                last_error = exc
                if self.debug:
                    print(
                        f"[API] {label} HTTP {exc.status} after "
                        f"{time.monotonic() - started:.1f}s",
                        file=sys.stderr, flush=True,
                    )
                if not self._should_retry_http_error(exc) or attempt >= self.retries:
                    break
                await self._sleep_before_retry(attempt, getattr(exc, "retry_after", None))
                attempt += 1
            except (TimeoutError, aiohttp.ClientError, RuntimeError, KeyError, json.JSONDecodeError) as exc:
                last_error = exc
                if self.debug:
                    print(
                        f"[API] {label} failed after "
                        f"{time.monotonic() - started:.1f}s: {exc}",
                        file=sys.stderr, flush=True,
                    )
                if attempt < self.retries:
                    await self._sleep_before_retry(attempt)
                    attempt += 1
                else:
                    break
        raise RuntimeError(f"远端 API 请求失败：{last_error}") from last_error

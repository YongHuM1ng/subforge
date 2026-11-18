"""OpenRouter 请求、重试、分片并发与语言识别。"""
from __future__ import annotations

import base64
import json
import random
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from common.net import resolve_proxy

from . import config, tui
from .util import log


class ApiError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(body)
        self.status = status
        self.body = body or ""

    def message(self) -> str:
        try:
            obj = json.loads(self.body)
            err = obj.get("error") if isinstance(obj, dict) else None
            if isinstance(err, dict):
                return str(err.get("message") or err)
            if err:
                return str(err)
        except Exception:
            pass
        return self.body.strip()[:500]


def _opener() -> urllib.request.OpenerDirector:
    """按 [asr] proxy（缺省回退 [api] proxy）构造带代理的 opener。"""
    proxy = resolve_proxy(config.API_URL, config.PROXY)
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    # 空 dict 表示显式直连，避免环境变量代理在“none”模式下仍然生效。
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _auth_headers(api_key: str) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if config.API_KEY_HEADER:
        headers[config.API_KEY_HEADER] = f"{config.API_KEY_PREFIX}{api_key}"
    return headers


def _post(url: str, data: bytes, headers: dict[str, str]) -> dict:
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with _opener().open(req, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode("utf-8", "replace")) from e
    except urllib.error.URLError as e:
        raise ApiError(0, str(e.reason)) from e


def _post_json(url: str, payload: dict, headers: dict[str, str]) -> dict:
    return _post(url, json.dumps(payload).encode("utf-8"), headers)


def _openai_multipart(wav_path: Path, api_key: str, mode: int) -> tuple[bytes, dict[str, str]]:
    """标准 OpenAI /audio/transcriptions 使用 multipart/form-data。"""
    boundary = "----SubForge" + uuid.uuid4().hex
    chunks: list[bytes] = []

    def field(name: str, value: str) -> None:
        chunks.append(
            (f"--{boundary}\r\n"
             f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
             f"{value}\r\n").encode()
        )

    field("model", config.MODEL)
    if mode >= 1:
        field("response_format", "verbose_json")
    if mode >= 2:
        field("timestamp_granularities[]", "word")
    if config.LANGUAGE:
        field("language", config.LANGUAGE)
    chunks.append(
        (f"--{boundary}\r\n"
         f'Content-Disposition: form-data; name="file"; filename="{wav_path.name}"\r\n'
         "Content-Type: audio/wav\r\n\r\n").encode()
        + wav_path.read_bytes() + b"\r\n"
    )
    chunks.append(f"--{boundary}--\r\n".encode())
    headers = _auth_headers(api_key)
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    return b"".join(chunks), headers


def _api_transcribe_openai(wav_path: Path, api_key: str, mode: int) -> dict:
    body, headers = _openai_multipart(wav_path, api_key, mode)
    return _post(config.API_URL, body, headers)


def _api_transcribe_transcriptions(wav_path: Path, api_key: str, mode: int) -> dict:
    """mode 2 = verbose_json + 词级时间戳；1 = 仅 verbose_json；0 = 纯文本。"""
    payload = {
        "model": config.MODEL,
        "input_audio": {
            "data": base64.b64encode(wav_path.read_bytes()).decode("ascii"),
            "format": "wav",
        },
    }
    if mode >= 1:
        payload["response_format"] = "verbose_json"
    if mode >= 2:
        payload["timestamp_granularities"] = ["word"]
    headers = _auth_headers(api_key)
    headers["X-Title"] = "asr2srt"
    return _post_json(config.API_URL, payload, headers)


def _content_text(content) -> str:
    if isinstance(content, str):
        text = content.strip()
        if text.startswith("{"):
            try:
                obj = json.loads(text)
            except ValueError:
                pass
            else:
                if isinstance(obj, dict):
                    for key in ("text", "transcript", "content"):
                        value = obj.get(key)
                        if isinstance(value, str):
                            return value.strip()
        return content.strip()
    if isinstance(content, dict):
        for key in ("text", "transcript", "content"):
            value = content.get(key)
            if isinstance(value, str):
                return value.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts).strip()
    return ""


def _extract_chat_text(data: dict) -> str:
    choices = data.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        choice = choices[0]
        message = choice.get("message")
        if isinstance(message, dict):
            audio = message.get("audio")
            if isinstance(audio, dict) and isinstance(audio.get("transcript"), str):
                return audio["transcript"].strip()
            text = _content_text(message.get("content"))
            if text:
                return text
        if isinstance(choice.get("text"), str):
            return choice["text"].strip()
    for key in ("text", "transcript"):
        value = data.get(key)
        if isinstance(value, str):
            return value.strip()
    return ""


def _api_transcribe_chat(wav_path: Path, api_key: str) -> dict:
    """OpenAI-compatible Chat Completions ASR：音频以 base64 放进 messages。"""
    audio = base64.b64encode(wav_path.read_bytes()).decode("ascii")
    if config.AUDIO_FORMAT == "base64":
        input_audio = {"data": audio, "format": "wav"}
    else:
        input_audio = {"data": f"data:audio/wav;base64,{audio}"}
    payload = {
        "model": config.MODEL,
        "stream": False,
        "messages": [{
            "role": "user",
            "content": [{
                "type": "input_audio",
                "input_audio": input_audio,
            }],
        }],
    }
    if config.LANGUAGE:
        payload["asr_options"] = {"language": config.LANGUAGE}
    data = _post_json(config.API_URL, payload, _auth_headers(api_key))
    out = {"text": _extract_chat_text(data)}
    if isinstance(data.get("usage"), dict):
        out["usage"] = data["usage"]
    if config.LANGUAGE:
        out["language"] = config.LANGUAGE
    return out


def api_transcribe(wav_path: Path, api_key: str, mode: int) -> dict:
    """按 [asr] protocol 选择请求方式。"""
    if config.PROTOCOL == "chat_completions":
        return _api_transcribe_chat(wav_path, api_key)
    if config.PROTOCOL == "openai_transcriptions":
        return _api_transcribe_openai(wav_path, api_key, mode)
    return _api_transcribe_transcriptions(wav_path, api_key, mode)


class Gate:
    """可动态缩小的并发闸门：遇到 402 预扣不足时自动降并发。"""

    def __init__(self, limit: int):
        self.limit = max(1, limit)
        self.active = 0
        self.cond = threading.Condition()
        self._last_shrink = 0.0

    def acquire(self) -> None:
        with self.cond:
            while self.active >= self.limit:
                self.cond.wait()
            self.active += 1

    def release(self) -> None:
        with self.cond:
            self.active = max(0, self.active - 1)
            self.cond.notify()

    def shrink(self) -> int:
        with self.cond:
            now = time.time()
            if now - self._last_shrink < 2.0:   # 同一波错误只降一次，避免直接降到 1
                return self.limit
            self._last_shrink = now
            self.limit = max(1, self.limit // 2)
            self.cond.notify_all()
            return self.limit


class UnsupportedParamError(RuntimeError):
    """接口不接受当前的时间戳参数；需要用户改 [asr] timestamps，不自动降级。"""


_NEXT_TIMESTAMPS = {2: "segment", 1: "none"}


def _unsupported_param_hint(mode: int, message: str) -> str | None:
    """400 是否明确指向时间戳相关参数；是则返回给用户的修改建议。"""
    low = message.lower()
    if mode >= 2 and "granularit" in low:
        param = "timestamp_granularities"
    elif mode >= 1 and ("response_format" in low or "verbose_json" in low):
        param = "response_format=verbose_json"
    else:
        return None
    current = next(name for name, value in config.TIMESTAMP_MODES.items() if value == mode)
    return (
        f"识别接口不接受 {param}（[asr] timestamps = \"{current}\"）：{message[:200]}；"
        f"请把 config.toml 的 [asr] timestamps 改为 \"{_NEXT_TIMESTAMPS[mode]}\" 后重试"
    )


def transcribe_chunk(wav_path: Path, api_key: str, state: dict) -> dict:
    attempt = 0
    mode = state["mode"]
    while True:
        gate = state.get("gate")
        if gate is not None:
            gate.acquire()
        try:
            return api_transcribe(wav_path, api_key, mode)
        except ApiError as exc:
            err = exc
        finally:
            if gate is not None:
                gate.release()

        msg = err.message()
        low = msg.lower()

        if err.status == 400 and mode > 0:
            hint = _unsupported_param_hint(mode, msg)
            if hint:
                raise UnsupportedParamError(hint) from err

        # 402 的 in-flight 变体：并发请求把额度预扣满了，不是真的没余额
        if err.status == 402 and ("in-flight" in low or "in flight" in low):
            if gate is not None and attempt < config.MAX_RETRY:
                new_limit = gate.shrink()
                delay = min(15.0, 2.0 + 2.0 * attempt) + random.uniform(0, 1.0)
                log(f"   [降并发] 请求预扣额度不足，并发降到 {new_limit}，{delay:.1f}s 后重试")
                time.sleep(delay)
                attempt += 1
                continue
            raise err

        retryable = err.status in (0, 408, 409, 425, 429, 500, 502, 503, 504)
        if retryable and attempt < config.MAX_RETRY:
            delay = min(30.0, 2.0 * (2 ** attempt)) + random.uniform(0, 1.0)
            log(f"   [重试] {err.status or '网络'} {msg[:120]} — {delay:.1f}s 后重试")
            time.sleep(delay)
            attempt += 1
            continue
        raise err


LANG_ALIASES = {
    "ja": "ja", "jp": "ja", "jpn": "ja", "japanese": "ja", "日本語": "ja", "日语": "ja",
    "en": "en", "eng": "en", "english": "en", "英语": "en", "英文": "en",
    "zh": "zh", "zho": "zh", "chi": "zh", "cmn": "zh", "yue": "zh",
    "chinese": "zh", "mandarin": "zh", "中文": "zh", "汉语": "zh",
    "ko": "ko", "kor": "ko", "korean": "ko", "한국어": "ko", "韩语": "ko",
    "fr": "fr", "fra": "fr", "fre": "fr", "french": "fr", "法语": "fr",
    "de": "de", "deu": "de", "ger": "de", "german": "de", "德语": "de",
    "es": "es", "spa": "es", "spanish": "es", "西班牙语": "es",
    "ru": "ru", "rus": "ru", "russian": "ru", "俄语": "ru",
    "pt": "pt", "por": "pt", "portuguese": "pt",
    "it": "it", "ita": "it", "italian": "it",
    "th": "th", "tha": "th", "thai": "th",
    "vi": "vi", "vie": "vi", "vietnamese": "vi",
}


def normalize_lang(value: str) -> str:
    """把 "Japanese" / "ja-JP" / "jp" 之类的值统一成 ISO 639-1 代码。"""
    v = (value or "").strip().lower()
    if not v:
        return ""
    if v in LANG_ALIASES:
        return LANG_ALIASES[v]
    if re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{2,8})*", v):
        return v.split("-")[0]
    return ""


def guess_lang(text: str) -> str:
    """接口没给 language 时，按字符特征猜一个。"""
    if re.search(r"[぀-ヿ]", text):
        return "ja"
    if re.search(r"[가-힯]", text):
        return "ko"
    han = len(re.findall(r"[一-鿿]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if han and han >= max(3, latin // 4):
        return "zh"
    if latin:
        return "en"
    return ""


def detect_language(results: list[tuple[float, float, dict]]) -> str:
    votes: dict[str, int] = {}
    for _, _, r in results:
        code = normalize_lang(str(r.get("language") or ""))
        if code:
            votes[code] = votes.get(code, 0) + 1
    if votes:
        return max(votes.items(), key=lambda kv: kv[1])[0]
    return guess_lang(" ".join(str(r.get("text") or "") for _, _, r in results))


def timing_supported(resp: dict) -> bool:
    """接口是否真的给出了可用的时间戳。

    有非空的 segments / words -> 支持；
    有文本但完全没有分段信息 -> 不支持（需要改用更短的定长切片）；
    整段静音（无文本）-> 无从判断，按支持处理，继续往下跑。
    """
    for key in ("segments", "words"):
        val = resp.get(key)
        if isinstance(val, list) and val:
            return True
    text = str(resp.get("text") or "").strip()
    if text:
        return False
    return True


def run_chunks(wavs: list[Path], chunks: list[tuple[float, float]],
               api_key: str, workers: int, probe_timing: bool = False,
               label: str = "", show_progress: bool = True):
    """
    返回 results 列表 [(start, end, resp), ...]；
    若 probe_timing=True 且接口完全不返回时间戳，返回 None 以示需要换切法。
    """
    state = {"mode": config.TIMESTAMP_MODES.get(config.TIMESTAMPS, 2), "gate": Gate(workers)}
    total = len(chunks)
    results: list[dict | None] = [None] * total

    def fetch(i: int) -> dict:
        return transcribe_chunk(wavs[i], api_key, state)

    t0 = time.time()

    def display(done: int) -> None:
        if show_progress:
            tui.write_progress(tui.progress_line(label, done, total, time.time() - t0))

    # 先串行处理首片（非静音的首片），用于判断接口是否给时间戳
    probe_idx = 0
    while probe_idx < total:
        resp = fetch(probe_idx)
        results[probe_idx] = resp
        if (resp.get("text") or "").strip() or (resp.get("segments") or resp.get("words")):
            break
        probe_idx += 1
    if probe_idx >= total:           # 整段都是静音
        return [(a, b, results[i] or {}) for i, (a, b) in enumerate(chunks)]
    if probe_timing and total > 1 and not timing_supported(results[probe_idx] or {}):
        return None

    done = sum(1 for r in results if r is not None)
    display(done)

    pending = [i for i in range(total) if results[i] is None]
    if pending:
        ex = ThreadPoolExecutor(max_workers=max(1, workers))
        try:
            futs = {ex.submit(fetch, i): i for i in pending}
            for fut in as_completed(futs):
                i = futs[fut]
                results[i] = fut.result()
                done += 1
                display(done)
        except BaseException:
            # 一片失败整份文件就作废：取消还没发出的请求，避免继续计费。
            ex.shutdown(wait=True, cancel_futures=True)
            if show_progress:
                tui.end_progress()
            raise
        ex.shutdown(wait=True)

    if show_progress:
        tui.write_progress(
            tui.progress_line(label, total, total, time.time() - t0), done=True)
    out = []
    for (a, b), r in zip(chunks, results, strict=False):
        if r is not None:
            out.append((a, b, r))
    return out


def summarize(results: list[tuple[float, float, dict]]) -> tuple[float, float, float]:
    secs = tokens = cost = 0.0
    for _, _, r in results:
        u = r.get("usage") or {}
        try:
            secs += float(u.get("seconds") or 0)
        except (TypeError, ValueError):
            pass
        try:
            tokens += float(u.get("total_tokens") or 0)
        except (TypeError, ValueError):
            pass
        try:
            cost += float(u.get("cost") or 0)
        except (TypeError, ValueError):
            pass
    if cost <= 0 and secs > 0:
        cost = secs / 3600.0 * config.PRICE_PER_HOUR
    return secs, tokens, cost

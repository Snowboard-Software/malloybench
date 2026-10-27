"""Gemini through the google-genai SDK, with a manual tool loop.

Settings (ModelConfig.settings):
  thinking_level:  minimal | low | medium | high  (Gemini 3 family)
  thinking_budget: integer token budget (0 turns thinking off where the model allows it)
  service_tier:    optional, e.g. "flex" (half price, slower)

The model's own Content (with its thought signatures) is appended unchanged, so the
reasoning carries across tool turns. Automatic function calling is off: the harness
runs every tool call itself.

The context shared by a dataset's tasks (system prompt, tools, model files and schema) goes
into an explicit context cache, created once per model and context and reused by every
attempt, because Gemini's implicit caching missed about half the time under parallel load.
The cache's storage is billed and recorded with the turn that creates it. When a cache
cannot be made (a context below the model's minimum size, say), the request carries the
context itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time

from google import genai  # pylint: disable=no-name-in-module  # installed in the benchmark venv, not the repo's
from google.genai import types  # pylint: disable=no-name-in-module  # same

from .base import CALL_RETRIES, CALL_TIMEOUT_S, Conversation, ModelConfig, ToolCall, ToolSpec, Turn, Usage

CACHE_TTL_S = 3600
CACHE_REUSE_S = 3300  # recreate a little before the provider expires it

_client: genai.Client | None = None
_caches: dict[str, tuple[str, float]] = {}
_cache_lock = threading.Lock()


def _get_client() -> genai.Client:
    global _client  # noqa: PLW0603 - one shared client per process
    if _client is None:
        _client = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(timeout=int(CALL_TIMEOUT_S * 1000), retry_options=types.HttpRetryOptions(attempts=CALL_RETRIES + 1)),
        )
    return _client


def _shared_cache(config: ModelConfig, system_text: str, tools: list[types.Tool] | None, tool_specs: list[ToolSpec]) -> tuple[str, float] | None:
    """The cache holding this system text and these tools for this model, and what creating
    it cost (0 when reused). None when the provider will not cache it."""
    key = hashlib.sha256(
        json.dumps([config.model_id, system_text, [(t.name, t.description, t.parameters) for t in tool_specs]], sort_keys=True).encode()
    ).hexdigest()
    with _cache_lock:
        hit = _caches.get(key)
        if hit and time.monotonic() - hit[1] < CACHE_REUSE_S:
            return hit[0], 0.0
        try:
            cache = _get_client().caches.create(
                model=config.model_id,
                config=types.CreateCachedContentConfig(system_instruction=system_text, tools=tools, ttl=f"{CACHE_TTL_S}s"),
            )
        except Exception:  # noqa: BLE001 - too small to cache, or caching unavailable: send the context instead
            return None
        tokens = (cache.usage_metadata.total_token_count or 0) if cache.usage_metadata else 0
        rate = config.pricing.cache_storage_per_hour or 0.0
        _caches[key] = (cache.name or "", time.monotonic())
        return cache.name or "", tokens / 1_000_000 * rate * CACHE_TTL_S / 3600


def _forget_cache(name: str) -> None:
    with _cache_lock:
        for key, (cached_name, _) in list(_caches.items()):
            if cached_name == name:
                del _caches[key]


class GeminiConversation(Conversation):
    def __init__(self, config: ModelConfig, system: str, tools: list[ToolSpec]):
        super().__init__(config, system, tools)
        self.contents: list[types.Content] = []
        self._tools = (
            [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(name=t.name, description=t.description, parameters_json_schema=t.parameters)
                        for t in tools
                    ]
                )
            ]
            if tools
            else None
        )
        self._call_counter = 0
        self._prefix = ""
        self._cache_name: str | None = None
        self._cache_decided = False

    def add_user_text(self, text: str, cached_prefix: str = "") -> None:
        if cached_prefix and not self.contents:
            self._prefix = cached_prefix
        elif cached_prefix:
            text = cached_prefix + "\n\n" + text
        self.contents.append(types.Content(role="user", parts=[types.Part.from_text(text=text)]))

    def add_tool_results(self, results: list[tuple[ToolCall, str, bool]]) -> None:
        parts = []
        for call, content, is_error in results:
            response = {"error": content} if is_error else {"result": content}
            part = types.Part.from_function_response(name=call.name, response=response)
            if part.function_response is not None and not call.id.startswith("local-"):
                part.function_response.id = call.id
            parts.append(part)
        self.contents.append(types.Content(role="user", parts=parts))

    def _thinking(self) -> types.ThinkingConfig | None:
        settings = self.config.settings
        if "thinking_level" in settings or "thinking_budget" in settings:
            return types.ThinkingConfig(thinking_level=settings.get("thinking_level"), thinking_budget=settings.get("thinking_budget"))
        return None

    def _request(self) -> tuple[list[types.Content], types.GenerateContentConfig]:
        common = {
            "thinking_config": self._thinking(),
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
            "max_output_tokens": self.config.max_output_tokens,
        }
        if self.config.settings.get("service_tier"):
            common["service_tier"] = self.config.settings["service_tier"]
        if self._cache_name:
            return self.contents, types.GenerateContentConfig(cached_content=self._cache_name, **common)
        contents = self.contents
        if self._prefix and contents:
            first = contents[0]
            contents = [types.Content(role="user", parts=[types.Part.from_text(text=self._prefix), *(first.parts or [])]), *contents[1:]]
        return contents, types.GenerateContentConfig(system_instruction=self.system, tools=self._tools, **common)

    def _send(self) -> Turn:
        storage_cost = 0.0
        if not self._cache_decided:
            self._cache_decided = True
            if self._prefix:
                shared = _shared_cache(self.config, self.system + "\n\n" + self._prefix, self._tools, self.tools)
                if shared:
                    self._cache_name, storage_cost = shared
        contents, config = self._request()
        try:
            response = _get_client().models.generate_content(model=self.config.model_id, contents=contents, config=config)
        except Exception as error:  # noqa: BLE001 - an expired or evicted cache is recreated once
            if not self._cache_name or "cache" not in str(error).lower():
                raise
            _forget_cache(self._cache_name)
            shared = _shared_cache(self.config, self.system + "\n\n" + self._prefix, self._tools, self.tools)
            self._cache_name, extra = shared if shared else (None, 0.0)
            storage_cost += extra
            contents, config = self._request()
            response = _get_client().models.generate_content(model=self.config.model_id, contents=contents, config=config)
        candidate = response.candidates[0] if response.candidates else None
        content = candidate.content if candidate else None
        if content is not None and content.parts:
            self.contents.append(content)
        else:
            # An empty candidate still has to occupy the model's turn.
            self.contents.append(types.Content(role="model", parts=[types.Part.from_text(text="")]))
        text_parts, calls = [], []
        for part in (content.parts if content and content.parts else []):
            if part.function_call is not None:
                self._call_counter += 1
                fc = part.function_call
                calls.append(
                    ToolCall(id=fc.id or f"local-{self._call_counter}", name=fc.name or "", arguments=dict(fc.args or {}))
                )
            elif part.text and not part.thought:
                text_parts.append(part.text)
        meta = response.usage_metadata
        prompt = (meta.prompt_token_count or 0) if meta else 0
        cached = (meta.cached_content_token_count or 0) if meta else 0
        thoughts = (meta.thoughts_token_count or 0) if meta else 0
        candidates = (meta.candidates_token_count or 0) if meta else 0
        tool_prompt = (meta.tool_use_prompt_token_count or 0) if meta else 0
        usage = Usage(
            input_tokens=prompt + tool_prompt - cached,
            cached_input_tokens=cached,
            output_tokens=candidates + thoughts,
            reasoning_tokens=thoughts,
        )
        finish = str(candidate.finish_reason.value if candidate and candidate.finish_reason else "")
        stop = "tool_use" if calls else finish.lower()
        return Turn(
            text="".join(text_parts),
            tool_calls=calls,
            usage=usage,
            stop_reason=stop,
            latency_s=0.0,
            extra_cost_usd=storage_cost,
            served_model=response.model_version or "",
        )

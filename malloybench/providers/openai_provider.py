"""OpenAI models through the Responses API, with a manual tool loop.

Settings (ModelConfig.settings):
  effort:       reasoning effort (none | minimal | low | medium | high | xhigh, per model)
  service_tier: optional, e.g. "flex" or "priority"; omitted means the default tier
  base_url / api_key_env: point the client at an OpenAI-compatible Responses endpoint
                (Azure's v1 API) instead of api.openai.com

Nothing is stored server-side (store=False). Reasoning items come back encrypted and
are replayed with the history, so a model keeps its reasoning across tool turns.
"""

from __future__ import annotations

import json
import os

import openai

from .base import CALL_RETRIES, CALL_TIMEOUT_S, Conversation, ModelConfig, ToolCall, ToolSpec, Turn, Usage

_clients: dict[tuple[str, str], openai.OpenAI] = {}


def _get_client(settings: dict) -> openai.OpenAI:
    base_url = settings.get("base_url", "")
    key_env = settings.get("api_key_env", "OPENAI_API_KEY")
    key = (base_url, key_env)
    if key not in _clients:
        _clients[key] = openai.OpenAI(
            api_key=os.environ[key_env], base_url=base_url or None, timeout=CALL_TIMEOUT_S, max_retries=CALL_RETRIES
        )
    return _clients[key]


class OpenAIConversation(Conversation):
    def __init__(self, config: ModelConfig, system: str, tools: list[ToolSpec]):
        super().__init__(config, system, tools)
        self.items: list = []
        self._tool_defs = [
            {"type": "function", "name": t.name, "description": t.description, "parameters": t.parameters, "strict": True}
            for t in tools
        ]

    def add_user_text(self, text: str, cached_prefix: str = "") -> None:
        content = [{"type": "input_text", "text": part} for part in (cached_prefix, text) if part]
        self.items.append({"role": "user", "content": content})

    def add_tool_results(self, results: list[tuple[ToolCall, str, bool]]) -> None:
        for call, content, is_error in results:
            self.items.append(
                {"type": "function_call_output", "call_id": call.id, "output": f"ERROR: {content}" if is_error else content}
            )

    def _send(self) -> Turn:
        settings = self.config.settings
        kwargs: dict = {
            "model": self.config.model_id,
            "instructions": self.system,
            "input": self.items,
            "max_output_tokens": self.config.max_output_tokens,
            "store": False,
            "include": ["reasoning.encrypted_content"],
        }
        if self._tool_defs:
            kwargs["tools"] = self._tool_defs
        if settings.get("effort"):
            kwargs["reasoning"] = {"effort": settings["effort"]}
        if settings.get("service_tier"):
            kwargs["service_tier"] = settings["service_tier"]
        if self.cache_key:
            kwargs["prompt_cache_key"] = self.cache_key
        response = _get_client(settings).responses.create(**kwargs)
        self.items.extend(item.model_dump(exclude_none=True) for item in response.output)
        calls = []
        for item in response.output:
            if item.type != "function_call":
                continue
            try:
                arguments = json.loads(item.arguments or "{}")
                calls.append(ToolCall(id=item.call_id, name=item.name, arguments=arguments, raw_arguments=item.arguments))
            except json.JSONDecodeError as error:
                calls.append(
                    ToolCall(id=item.call_id, name=item.name, arguments={}, raw_arguments=item.arguments, parse_error=str(error))
                )
        u = response.usage
        cached = (u.input_tokens_details.cached_tokens or 0) if u and u.input_tokens_details else 0
        reasoning = (u.output_tokens_details.reasoning_tokens or 0) if u and u.output_tokens_details else 0
        usage = Usage(
            input_tokens=(u.input_tokens - cached) if u else 0,
            cached_input_tokens=cached,
            output_tokens=u.output_tokens if u else 0,
            reasoning_tokens=reasoning,
        )
        stop = response.status or ""
        if response.incomplete_details and response.incomplete_details.reason:
            stop = response.incomplete_details.reason
        elif calls:
            stop = "tool_use"
        return Turn(
            text=response.output_text or "", tool_calls=calls, usage=usage, stop_reason=stop, latency_s=0.0, served_model=response.model or ""
        )

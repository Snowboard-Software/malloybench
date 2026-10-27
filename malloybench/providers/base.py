"""The provider-neutral conversation interface every model adapter implements.

An adapter keeps its provider's native message history and only ever appends to it:
some providers bind reasoning state to the exact history that produced it, so an
edited history can silently drop or reject that state.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

# Per provider call. Long enough for a high-effort reply; short enough that a stalled
# connection (seen: Anthropic calls that never returned) cannot hold a worker for long.
CALL_TIMEOUT_S = 300.0
CALL_RETRIES = 2
from dataclasses import asdict, dataclass, field


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON Schema with additionalProperties: false and every property required


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    raw_arguments: str = ""
    parse_error: str = ""


@dataclass
class Usage:
    input_tokens: int = 0  # billed at the full input rate (excludes cached reads and cache writes)
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0  # includes reasoning tokens
    reasoning_tokens: int = 0  # informational; already inside output_tokens

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.cached_input_tokens += other.cached_input_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.output_tokens += other.output_tokens
        self.reasoning_tokens += other.reasoning_tokens


@dataclass
class Turn:
    text: str
    tool_calls: list[ToolCall]
    usage: Usage
    stop_reason: str
    latency_s: float
    cost_usd: float = 0.0
    provider_reported_cost_usd: float | None = None
    extra_cost_usd: float = 0.0  # billed outside token usage, such as a context cache's storage
    served_model: str = ""  # the model the provider says answered, which can differ from the one asked for

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Pricing:
    """USD per million tokens."""

    input: float
    output: float
    cached_input: float | None = None
    cache_write: float | None = None
    cache_storage_per_hour: float | None = None  # USD per million cached tokens per hour (Gemini)

    def cost(self, usage: Usage) -> float:
        cached = self.cached_input if self.cached_input is not None else self.input
        write = self.cache_write if self.cache_write is not None else self.input
        return (
            usage.input_tokens * self.input
            + usage.cached_input_tokens * cached
            + usage.cache_write_tokens * write
            + usage.output_tokens * self.output
        ) / 1_000_000


@dataclass
class ModelConfig:
    key: str  # roster name, e.g. "gpt-5.6-luna@low"
    provider: str  # anthropic | openai | gemini | openrouter | fireworks
    model_id: str
    pricing: Pricing
    settings: dict = field(default_factory=dict)  # provider-specific reasoning settings
    max_output_tokens: int = 16000
    retry_max_output_tokens: int = 0  # an attempt cut off at max_output_tokens is retried with this cap
    label: str = ""


class Conversation(ABC):
    """One task attempt with one model. Not thread-safe; one per worker."""

    def __init__(self, config: ModelConfig, system: str, tools: list[ToolSpec]):
        self.config = config
        self.system = system
        self.tools = tools
        self.cache_key = ""  # groups requests that share a prompt prefix (OpenAI routing hint)

    @abstractmethod
    def add_user_text(self, text: str, cached_prefix: str = "") -> None:
        """Append a user message. `cached_prefix` is context shared by many tasks (model files,
        schema); it goes first and, where the provider takes explicit breakpoints, is cached."""

    @abstractmethod
    def add_tool_results(self, results: list[tuple[ToolCall, str, bool]]) -> None:
        """Append one result per call of the previous turn: (call, content, is_error)."""

    @abstractmethod
    def _send(self) -> Turn: ...

    def send(self) -> Turn:
        started = time.monotonic()
        turn = self._send()
        turn.latency_s = time.monotonic() - started
        # A provider that reports what the call cost (OpenRouter) is believed over our estimate.
        estimate = self.config.pricing.cost(turn.usage)
        tokens_cost = turn.provider_reported_cost_usd if turn.provider_reported_cost_usd is not None else estimate
        turn.cost_usd = tokens_cost + turn.extra_cost_usd
        return turn

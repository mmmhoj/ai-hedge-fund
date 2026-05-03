from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

COST_PER_1M_INPUT_USD: dict[str, float] = {
    "gpt-4o": 2.50,
    "gpt-4o-2024-08-06": 2.50,
    "gpt-4o-mini": 0.15,
    "gpt-4-turbo": 10.00,
    "gpt-4.1": 2.00,
    "gpt-4.1-mini": 0.40,
    "gpt-3.5-turbo": 0.50,
    "claude-3-5-sonnet-20241022": 3.00,
    "claude-3-5-haiku-20241022": 0.80,
    "claude-sonnet-4-5": 3.00,
    "deepseek-chat": 0.27,
    "llama-3.1-70b-versatile": 0.59,
    "llama-3.1-8b-instant": 0.05,
}
COST_PER_1M_OUTPUT_USD: dict[str, float] = {
    "gpt-4o": 10.00,
    "gpt-4o-2024-08-06": 10.00,
    "gpt-4o-mini": 0.60,
    "gpt-4-turbo": 30.00,
    "gpt-4.1": 8.00,
    "gpt-4.1-mini": 1.60,
    "gpt-3.5-turbo": 1.50,
    "claude-3-5-sonnet-20241022": 15.00,
    "claude-3-5-haiku-20241022": 4.00,
    "claude-sonnet-4-5": 15.00,
    "deepseek-chat": 1.10,
    "llama-3.1-70b-versatile": 0.79,
    "llama-3.1-8b-instant": 0.08,
}
DEFAULT_INPUT_COST = 2.50
DEFAULT_OUTPUT_COST = 10.00

_CURRENT_TRACKER: ContextVar["AgentCostTracker | None"] = ContextVar(
    "agent_cost_tracker",
    default=None,
)


@dataclass
class AgentCostRecord:
    agent_id: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_usd: float = 0.0
    call_count: int = 0


class AgentCostTracker:
    def __init__(self) -> None:
        self._records: dict[str, AgentCostRecord] = {}
        self._current_agent: str | None = None

    def set_current_agent(self, agent_id: str) -> None:
        self._current_agent = agent_id
        self._records.setdefault(agent_id, AgentCostRecord(agent_id=agent_id))

    def record_call(
        self,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        agent_id = self._current_agent or "_unattributed"
        record = self._records.setdefault(agent_id, AgentCostRecord(agent_id=agent_id))
        record.prompt_tokens += prompt_tokens
        record.completion_tokens += completion_tokens
        record.total_tokens += prompt_tokens + completion_tokens
        record.call_count += 1

        input_cost = COST_PER_1M_INPUT_USD.get(model_name, DEFAULT_INPUT_COST) / 1_000_000
        output_cost = COST_PER_1M_OUTPUT_USD.get(model_name, DEFAULT_OUTPUT_COST) / 1_000_000
        record.total_usd += prompt_tokens * input_cost + completion_tokens * output_cost

    @property
    def total_usd(self) -> float:
        return sum(record.total_usd for record in self._records.values())

    def by_agent_usd(self) -> dict[str, float]:
        return {
            record.agent_id: round(record.total_usd, 6)
            for record in self._records.values()
        }

    def total_tokens(self) -> int:
        return sum(record.total_tokens for record in self._records.values())


def get_current_tracker() -> AgentCostTracker | None:
    return _CURRENT_TRACKER.get()


@contextmanager
def track_costs() -> Iterator[AgentCostTracker]:
    tracker = AgentCostTracker()
    token = _CURRENT_TRACKER.set(tracker)
    try:
        yield tracker
    finally:
        _CURRENT_TRACKER.reset(token)


class CommitteeCostCallback(BaseCallbackHandler):
    def __init__(self, tracker: AgentCostTracker, model_name: str) -> None:
        super().__init__()
        self.tracker = tracker
        self.model_name = model_name

    def on_llm_end(self, response: LLMResult, **kwargs: object) -> None:
        usage = self._extract_usage(response)
        if usage is None:
            return

        prompt_tokens, completion_tokens = usage
        model_name = self._extract_model_name(response) or self.model_name
        self.tracker.record_call(model_name, prompt_tokens, completion_tokens)

    @staticmethod
    def _extract_usage(response: LLMResult) -> tuple[int, int] | None:
        output = getattr(response, "llm_output", None) or {}
        token_usage = output.get("token_usage") or output.get("usage") or {}
        prompt = token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0
        completion = token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0

        if prompt == 0 and completion == 0:
            for generation_list in getattr(response, "generations", []) or []:
                for generation in generation_list:
                    gen_info = getattr(generation, "generation_info", None) or {}
                    prompt = prompt or gen_info.get("prompt_tokens", 0)
                    prompt = prompt or gen_info.get("input_tokens", 0)
                    completion = completion or gen_info.get("completion_tokens", 0)
                    completion = completion or gen_info.get("output_tokens", 0)

        if prompt == 0 and completion == 0:
            return None
        return int(prompt), int(completion)

    @staticmethod
    def _extract_model_name(response: LLMResult) -> str | None:
        output = getattr(response, "llm_output", None) or {}
        return output.get("model_name") or output.get("model")

from __future__ import annotations

import pytest
from langchain_core.outputs import Generation, LLMResult

from src.tools.cost_tracker import (
    DEFAULT_INPUT_COST,
    AgentCostTracker,
    CommitteeCostCallback,
    get_current_tracker,
    track_costs,
)


def test_agent_cost_tracker_initial_state() -> None:
    tracker = AgentCostTracker()

    assert tracker.total_usd == 0.0
    assert tracker.by_agent_usd() == {}


def test_agent_cost_tracker_records_call() -> None:
    tracker = AgentCostTracker()
    tracker.set_current_agent("warren_buffett")

    tracker.record_call("gpt-4o", 1000, 500)

    expected = 1000 * 2.50 / 1_000_000 + 500 * 10.00 / 1_000_000
    assert tracker.by_agent_usd()["warren_buffett"] == pytest.approx(expected)
    assert tracker.total_usd == pytest.approx(expected)


def test_agent_cost_tracker_unknown_model_uses_default() -> None:
    tracker = AgentCostTracker()
    tracker.set_current_agent("warren_buffett")

    tracker.record_call("unknown-model", 1000, 0)

    expected = 1000 * DEFAULT_INPUT_COST / 1_000_000
    assert tracker.by_agent_usd()["warren_buffett"] == pytest.approx(expected)


def test_agent_cost_tracker_multiple_agents() -> None:
    tracker = AgentCostTracker()

    tracker.set_current_agent("warren_buffett")
    tracker.record_call("gpt-4o", 1000, 500)
    tracker.set_current_agent("ben_graham")
    tracker.record_call("gpt-4o-mini", 2000, 1000)

    warren_cost = 1000 * 2.50 / 1_000_000 + 500 * 10.00 / 1_000_000
    ben_cost = 2000 * 0.15 / 1_000_000 + 1000 * 0.60 / 1_000_000
    by_agent = tracker.by_agent_usd()

    assert by_agent["warren_buffett"] == pytest.approx(warren_cost)
    assert by_agent["ben_graham"] == pytest.approx(ben_cost)
    assert tracker.total_usd == pytest.approx(warren_cost + ben_cost)


def test_agent_cost_tracker_unattributed_call() -> None:
    tracker = AgentCostTracker()

    tracker.record_call("gpt-4o", 1000, 0)

    expected = 1000 * 2.50 / 1_000_000
    assert tracker.by_agent_usd()["_unattributed"] == pytest.approx(expected)


def test_track_costs_context_manager() -> None:
    assert get_current_tracker() is None

    with track_costs() as tracker:
        assert get_current_tracker() is tracker

    assert get_current_tracker() is None


def test_track_costs_resets_on_exception() -> None:
    with pytest.raises(RuntimeError):
        with track_costs():
            assert get_current_tracker() is not None
            raise RuntimeError("boom")

    assert get_current_tracker() is None


def test_committee_cost_callback_extracts_usage() -> None:
    tracker = AgentCostTracker()
    tracker.set_current_agent("warren_buffett")
    callback = CommitteeCostCallback(tracker, "gpt-4o-mini")
    response = LLMResult(
        generations=[],
        llm_output={
            "token_usage": {"prompt_tokens": 100, "completion_tokens": 50},
            "model_name": "gpt-4o",
        },
    )

    callback.on_llm_end(response)

    expected = 100 * 2.50 / 1_000_000 + 50 * 10.00 / 1_000_000
    assert tracker.by_agent_usd()["warren_buffett"] == pytest.approx(expected)


def test_committee_cost_callback_falls_back_to_generation_info() -> None:
    tracker = AgentCostTracker()
    tracker.set_current_agent("warren_buffett")
    callback = CommitteeCostCallback(tracker, "gpt-4o")
    response = LLMResult(
        generations=[
            [Generation(text="{}", generation_info={"prompt_tokens": 100, "completion_tokens": 50})]
        ],
        llm_output={},
    )

    callback.on_llm_end(response)

    expected = 100 * 2.50 / 1_000_000 + 50 * 10.00 / 1_000_000
    assert tracker.by_agent_usd()["warren_buffett"] == pytest.approx(expected)


def test_committee_cost_callback_no_usage_returns_silently() -> None:
    tracker = AgentCostTracker()
    callback = CommitteeCostCallback(tracker, "gpt-4o")
    response = LLMResult(generations=[], llm_output={})

    callback.on_llm_end(response)

    assert tracker.total_usd == 0.0
    assert tracker.by_agent_usd() == {}

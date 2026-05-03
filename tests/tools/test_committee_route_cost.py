from __future__ import annotations

from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from app.backend.routes import committee


class FakeCompiledWorkflow:
    def __init__(self, invoke_fn: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self.invoke_fn = invoke_fn

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        return self.invoke_fn(state)


class FakeWorkflow:
    def __init__(self, invoke_fn: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self.invoke_fn = invoke_fn

    def compile(self) -> FakeCompiledWorkflow:
        return FakeCompiledWorkflow(self.invoke_fn)


def _client() -> TestClient:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(committee.router)
    return TestClient(app)


def _patch_cost_workflow(monkeypatch) -> None:
    def fake_invoke(state: dict[str, Any]) -> dict[str, Any]:
        from src.tools.cost_tracker import get_current_tracker

        tracker = get_current_tracker()
        assert tracker is not None
        tracker.set_current_agent("warren_buffett")
        tracker.record_call("gpt-4o", 1000, 500)
        tracker.set_current_agent("ben_graham")
        tracker.record_call("gpt-4o-mini", 2000, 1000)
        return {"data": {"analyst_signals": {}}}

    monkeypatch.setattr(
        committee,
        "create_workflow",
        lambda selected_analysts: FakeWorkflow(fake_invoke),
    )


def test_committee_route_records_cost_via_callback(monkeypatch) -> None:
    _patch_cost_workflow(monkeypatch)

    response = _client().post(
        "/committee/run",
        json={
            "tickers": ["AAPL"],
            "start_date": "2026-04-01",
            "end_date": "2026-05-01",
            "agent_set": ["warren_buffett", "ben_graham"],
            "cost_cap_usd": 0.05,
        },
    )

    assert response.status_code == 200
    body = response.json()
    warren_cost = 0.0075
    ben_cost = 0.0009

    assert body["cost_breakdown"]["total_usd"] == pytest.approx(warren_cost + ben_cost)
    assert body["cost_breakdown"]["by_agent"]["warren_buffett"] == pytest.approx(warren_cost)
    assert body["cost_breakdown"]["by_agent"]["ben_graham"] == pytest.approx(ben_cost)
    assert body["cost_breakdown"]["truncated"] is False
    assert body["cost_breakdown"]["truncation_reason"] is None


def test_committee_route_truncated_when_over_cap(monkeypatch) -> None:
    _patch_cost_workflow(monkeypatch)

    response = _client().post(
        "/committee/run",
        json={
            "tickers": ["AAPL"],
            "start_date": "2026-04-01",
            "end_date": "2026-05-01",
            "agent_set": ["warren_buffett", "ben_graham"],
            "cost_cap_usd": 0.005,
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["cost_breakdown"]["total_usd"] == pytest.approx(0.0084)
    assert body["cost_breakdown"]["truncated"] is True
    assert "cap" in body["cost_breakdown"]["truncation_reason"]

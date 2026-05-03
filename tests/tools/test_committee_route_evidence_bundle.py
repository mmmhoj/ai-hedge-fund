from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.backend.routes import committee
from src.tools import evidence_bundle_context


def price_row() -> dict[str, Any]:
    return {
        "open": 100.0,
        "close": 101.0,
        "high": 102.0,
        "low": 99.0,
        "volume": 1000,
        "time": "2024-01-02T00:00:00Z",
    }


class FakeCompiledWorkflow:
    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        bundle = evidence_bundle_context.get_current_bundle()
        marker = str(bundle.get("sha256")) if bundle is not None else "missing"
        return {
            "data": {
                "analyst_signals": {
                    "warren_buffett_agent": {
                        "AAPL": {
                            "signal": "bullish",
                            "confidence": 80,
                            "reasoning": marker,
                        }
                    }
                }
            }
        }


class FakeWorkflow:
    def compile(self) -> FakeCompiledWorkflow:
        return FakeCompiledWorkflow()


def _client() -> TestClient:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(committee.router)
    return TestClient(app)


def test_committee_route_uses_bundle_during_invoke(monkeypatch) -> None:
    marker = "x" * 64

    def fake_create_workflow(selected_analysts: list[str]) -> FakeWorkflow:
        return FakeWorkflow()

    monkeypatch.setattr(committee, "create_workflow", fake_create_workflow)

    response = _client().post(
        "/committee/run",
        json={
            "tickers": ["AAPL"],
            "start_date": "2026-04-01",
            "end_date": "2026-05-01",
            "agent_set": ["warren_buffett"],
            "evidence_bundle": {
                "prices": {"AAPL": [price_row()]},
                "sha256": marker,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["signals"][0]["rationale"] == marker

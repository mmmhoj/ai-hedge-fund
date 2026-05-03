from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from app.backend.database import get_db
from app.backend.models.events import CompleteEvent
from app.backend.routes import hedge_fund
from src.tools import evidence_bundle_context


class FakeCompiledGraph:
    async def ainvoke(self, _state: dict[str, Any]) -> dict[str, Any]:
        bundle = evidence_bundle_context.get_current_bundle()
        marker = str(bundle.get("sha256")) if bundle is not None else "missing"
        return {
            "decisions": {"AAPL": {"action": "hold", "quantity": 0}},
            "analyst_signals": {
                "warren_buffett_agent": {
                    "AAPL": {
                        "signal": "neutral",
                        "confidence": 50,
                        "reasoning": marker,
                    }
                }
            },
            "current_prices": {"AAPL": 100.0},
        }


class FakeGraph:
    def compile(self) -> FakeCompiledGraph:
        return FakeCompiledGraph()


def _client() -> TestClient:
    from fastapi import FastAPI

    def empty_db():
        yield None

    app = FastAPI()
    app.dependency_overrides[get_db] = empty_db
    app.include_router(hedge_fund.router)
    return TestClient(app)


def _request_payload(evidence_bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tickers": ["AAPL"],
        "graph_nodes": [{"id": "warren_buffett"}],
        "graph_edges": [],
        "start_date": "2026-04-01",
        "end_date": "2026-05-01",
        "api_keys": {"OPENAI_API_KEY": "test"},
    }
    if evidence_bundle is not None:
        payload["evidence_bundle"] = evidence_bundle
    return payload


def _sse_event_data(stream: str, event_name: str) -> str:
    for event in stream.split("\n\n"):
        lines = event.splitlines()
        if not lines or lines[0] != f"event: {event_name}":
            continue
        data_lines = [
            line[len("data: ") :]
            for line in lines[1:]
            if line.startswith("data: ")
        ]
        return "\n".join(data_lines)
    raise AssertionError(f"Missing SSE event {event_name!r} in stream:\n{stream}")


def _patch_graph_run(monkeypatch, record_cost: bool = False) -> None:
    def fake_create_graph(graph_nodes, graph_edges):
        return FakeGraph()

    async def fake_run_graph_async(
        graph,
        portfolio,
        tickers,
        start_date,
        end_date,
        model_name,
        model_provider,
        request=None,
    ):
        if record_cost:
            from src.tools.cost_tracker import get_current_tracker

            tracker = get_current_tracker()
            assert tracker is not None
            tracker.set_current_agent("warren_buffett")
            tracker.record_call("gpt-4o", 1000, 500)

        data = await graph.ainvoke({})
        return {
            "messages": [type("Msg", (), {"content": json.dumps(data["decisions"])})()],
            "data": {
                "analyst_signals": data["analyst_signals"],
                "current_prices": data["current_prices"],
            },
        }

    monkeypatch.setattr(hedge_fund, "create_graph", fake_create_graph)
    monkeypatch.setattr(hedge_fund, "run_graph_async", fake_run_graph_async)


def test_hedge_fund_run_uses_evidence_bundle(monkeypatch) -> None:
    marker = "x" * 64
    _patch_graph_run(monkeypatch)

    response = _client().post(
        "/hedge-fund/run",
        json=_request_payload(evidence_bundle={"sha256": marker}),
    )

    assert response.status_code == 200
    assert marker in response.text


def test_hedge_fund_run_records_cost_via_callback(monkeypatch) -> None:
    _patch_graph_run(monkeypatch, record_cost=True)

    response = _client().post("/hedge-fund/run", json=_request_payload())

    assert response.status_code == 200
    cost = json.loads(_sse_event_data(response.text, "cost"))
    assert cost["total_usd"] > 0
    assert cost["by_agent"]["warren_buffett"] > 0

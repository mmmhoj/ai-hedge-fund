from typing import Any

from fastapi.testclient import TestClient

from app.backend.routes import committee


DEFAULT_AGENTS = ["warren_buffett", "ben_graham", "peter_lynch"]


class FakeCompiledWorkflow:
    def __init__(self, analyst_signals: dict[str, Any]) -> None:
        self.analyst_signals = analyst_signals
        self.invoke_state: dict[str, Any] | None = None

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        self.invoke_state = state
        return {"data": {"analyst_signals": self.analyst_signals}}


class FakeWorkflow:
    def __init__(
        self,
        analyst_signals: dict[str, Any],
        compile_error: Exception | None = None,
    ) -> None:
        self.compiled = FakeCompiledWorkflow(analyst_signals)
        self.compile_error = compile_error

    def compile(self) -> FakeCompiledWorkflow:
        if self.compile_error is not None:
            raise self.compile_error
        return self.compiled


def _client() -> TestClient:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(committee.router)
    return TestClient(app)


def _patch_workflow(
    monkeypatch,
    analyst_signals: dict[str, Any],
    compile_error: Exception | None = None,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_create_workflow(selected_analysts: list[str]) -> FakeWorkflow:
        workflow = FakeWorkflow(analyst_signals, compile_error)
        captured["selected_analysts"] = selected_analysts
        captured["workflow"] = workflow
        return workflow

    monkeypatch.setattr(committee, "create_workflow", fake_create_workflow)
    return captured


def _post_with_signal(
    monkeypatch,
    signal: str,
    confidence: int = 80,
    ticker: str = "AAPL",
) -> dict[str, Any]:
    _patch_workflow(
        monkeypatch,
        {
            "warren_buffett_agent": {
                ticker: {
                    "signal": signal,
                    "confidence": confidence,
                    "reasoning": "Strong moat",
                }
            }
        },
    )
    response = _client().post(
        "/committee/run",
        json={
            "tickers": [ticker],
            "start_date": "2026-04-01",
            "end_date": "2026-05-01",
            "agent_set": ["warren_buffett"],
        },
    )

    assert response.status_code == 200
    return response.json()


def test_committee_run_invokes_agents_with_default_set(monkeypatch) -> None:
    captured = _patch_workflow(
        monkeypatch,
        {
            "warren_buffett_agent": {
                "AAPL": {
                    "signal": "bullish",
                    "confidence": 80,
                    "reasoning": "Strong moat",
                }
            }
        },
    )

    response = _client().post(
        "/committee/run",
        json={
            "tickers": ["AAPL"],
            "start_date": "2026-04-01",
            "end_date": "2026-05-01",
            "agent_set": [],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["agents_run"] == DEFAULT_AGENTS
    assert len(body["signals"]) == 1
    assert captured["selected_analysts"] == DEFAULT_AGENTS

    invoke_state = captured["workflow"].compiled.invoke_state
    assert invoke_state["data"]["tickers"] == ["AAPL"]
    assert invoke_state["data"]["portfolio"]["cash"] == 1_000_000
    assert invoke_state["data"]["portfolio"]["positions"]["AAPL"]["long"] == 0


def test_committee_run_maps_bullish_to_buy(monkeypatch) -> None:
    body = _post_with_signal(monkeypatch, "bullish")

    assert body["signals"][0]["action"] == "buy"


def test_committee_run_maps_bearish_to_trim(monkeypatch) -> None:
    body = _post_with_signal(monkeypatch, "bearish")

    assert body["signals"][0]["action"] == "trim"


def test_committee_run_maps_neutral_to_hold(monkeypatch) -> None:
    body = _post_with_signal(monkeypatch, "neutral")

    assert body["signals"][0]["action"] == "hold"


def test_committee_run_confidence_normalized(monkeypatch) -> None:
    body = _post_with_signal(monkeypatch, "bullish", confidence=75)

    assert body["signals"][0]["confidence"] == 0.75


def test_committee_run_with_explicit_agent_set(monkeypatch) -> None:
    captured = _patch_workflow(
        monkeypatch,
        {
            "warren_buffett_agent": {
                "AAPL": {
                    "signal": "bullish",
                    "confidence": 80,
                    "reasoning": "Strong moat",
                }
            },
            "ben_graham_agent": {
                "AAPL": {
                    "signal": "neutral",
                    "confidence": 50,
                    "reasoning": "Margin of safety is thin",
                }
            },
        },
    )

    response = _client().post(
        "/committee/run",
        json={
            "tickers": ["AAPL"],
            "start_date": "2026-04-01",
            "end_date": "2026-05-01",
            "agent_set": ["warren_buffett"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert captured["selected_analysts"] == ["warren_buffett"]
    assert body["agents_run"] == ["warren_buffett"]
    assert [signal["persona_id"] for signal in body["signals"]] == ["warren_buffett"]


def test_committee_run_unknown_agent_returns_400() -> None:
    response = _client().post(
        "/committee/run",
        json={
            "tickers": ["AAPL"],
            "start_date": "2026-04-01",
            "end_date": "2026-05-01",
            "agent_set": ["unknown_agent"],
        },
    )

    assert response.status_code == 400


def test_committee_run_workflow_failure_returns_failed_data(monkeypatch) -> None:
    _patch_workflow(monkeypatch, {}, compile_error=RuntimeError("build failed"))

    response = _client().post(
        "/committee/run",
        json={
            "tickers": ["AAPL"],
            "start_date": "2026-04-01",
            "end_date": "2026-05-01",
            "agent_set": ["warren_buffett"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_status"] == "failed_data"
    assert body["signals"] == []
    assert body["error_message"]


def test_committee_run_kr_ticker_canonical_id(monkeypatch) -> None:
    body = _post_with_signal(monkeypatch, "bullish", ticker="005930")

    assert body["signals"][0]["asset_canonical_id"].endswith(".KRX")


def test_committee_run_us_ticker_canonical_id(monkeypatch) -> None:
    body = _post_with_signal(monkeypatch, "bullish", ticker="AAPL")

    assert body["signals"][0]["asset_canonical_id"].endswith(".NASDAQ")

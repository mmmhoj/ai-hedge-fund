from fastapi.testclient import TestClient

from app.backend.routes import committee


def _patch_empty_workflow(monkeypatch) -> None:
    class FakeAgent:
        def invoke(self, state):
            return {"data": {"analyst_signals": {}}}

    class FakeWorkflow:
        def compile(self):
            return FakeAgent()

    monkeypatch.setattr(
        committee,
        "create_workflow",
        lambda selected_analysts: FakeWorkflow(),
    )


def _client() -> TestClient:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(committee.router)
    return TestClient(app)


def test_committee_run_accepts_minimal_request(monkeypatch) -> None:
    _patch_empty_workflow(monkeypatch)

    response = _client().post(
        "/committee/run",
        json={
            "tickers": ["AAPL"],
            "start_date": "2026-04-01",
            "end_date": "2026-05-01",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_status"] == "ok"
    assert body["signals"] == []
    assert body["agents_run"] == ["warren_buffett", "ben_graham", "peter_lynch"]
    assert body["cost_breakdown"]["total_usd"] == 0.0


def test_committee_run_rejects_empty_tickers() -> None:
    response = _client().post(
        "/committee/run",
        json={
            "tickers": [],
            "start_date": "2026-04-01",
            "end_date": "2026-05-01",
        },
    )

    assert response.status_code == 400


def test_committee_run_propagates_evidence_bundle_sha256(monkeypatch) -> None:
    _patch_empty_workflow(monkeypatch)

    response = _client().post(
        "/committee/run",
        json={
            "tickers": ["005930"],
            "start_date": "2026-04-01",
            "end_date": "2026-05-01",
            "agent_set": ["warren_buffett", "ben_graham"],
            "evidence_bundle": {"sha256": "deadbeef" * 8},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["bundle_sha256"] == "deadbeef" * 8
    assert body["agents_run"] == ["warren_buffett", "ben_graham"]

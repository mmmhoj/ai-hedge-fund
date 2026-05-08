from __future__ import annotations

from v2.data import FDClient


class _FakeResponse:
    status_code = 200

    def json(self) -> dict:
        return {
            "results": [
                {
                    "date": "2025-01-02",
                    "open": 589.39,
                    "high": 591.13,
                    "low": 580.5,
                    "close": 584.64,
                    "volume": 50204000,
                }
            ],
            "provider": "yfinance",
        }


def test_prices_fall_back_to_openbb_when_fd_returns_no_data(monkeypatch) -> None:
    seen: dict = {}

    def fake_get(url, *, params, timeout):
        seen["url"] = url
        seen["params"] = params
        seen["timeout"] = timeout
        return _FakeResponse()

    client = FDClient(
        api_key="test-key",
        timeout=30.0,
        openbb_api_base="http://openbb.test/api/v1",
    )
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: None)
    monkeypatch.setattr("v2.data.client.requests.get", fake_get)

    prices = client.get_prices("SPY", "2025-01-01", "2025-01-10")

    assert seen["url"] == "http://openbb.test/api/v1/equity/price/historical"
    assert seen["params"] == {
        "symbol": "SPY",
        "provider": "yfinance",
        "start_date": "2025-01-01",
        "end_date": "2025-01-10",
    }
    assert prices[0].time == "2025-01-02T00:00:00"
    assert prices[0].close == 584.64
    assert prices[0].volume == 50204000

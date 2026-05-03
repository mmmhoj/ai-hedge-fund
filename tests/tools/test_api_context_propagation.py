from __future__ import annotations

from unittest.mock import Mock

import pytest

from src.data.models import FinancialMetrics, Price
from src.tools import api, api_kr
from src.tools.evidence_bundle_context import use_bundle


def price_row(close: float = 101.0) -> dict:
    return {
        "open": 100.0,
        "close": close,
        "high": 102.0,
        "low": 99.0,
        "volume": 1000,
        "time": "2024-01-02T00:00:00Z",
    }


def financial_metrics_row(return_on_equity: float = 0.25) -> dict:
    row = {field: None for field in FinancialMetrics.model_fields}
    row.update(
        {
            "ticker": "AAPL",
            "report_period": "2024-03-31",
            "period": "ttm",
            "currency": "USD",
            "market_cap": 1230000.0,
            "return_on_equity": return_on_equity,
        }
    )
    return row


def response(payload: dict) -> Mock:
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = payload
    return mock_response


def fail_request(*args, **kwargs):
    pytest.fail("network fetch should not be called")


def patch_price_cache_miss(monkeypatch) -> None:
    monkeypatch.setattr(api._cache, "get_prices", lambda cache_key: None)
    monkeypatch.setattr(api._cache, "set_prices", lambda cache_key, data: None)


def test_get_prices_uses_contextvar_bundle(monkeypatch) -> None:
    row = price_row()
    monkeypatch.setattr(api, "_make_api_request", fail_request)

    with use_bundle({"prices": {"AAPL": [row]}}):
        result = api.get_prices("AAPL", "2024-01-01", "2024-01-02")

    assert [price.model_dump() for price in result] == [row]


def test_get_financial_metrics_uses_contextvar_bundle(monkeypatch) -> None:
    row = financial_metrics_row()
    monkeypatch.setattr(api, "_make_api_request", fail_request)

    with use_bundle({"fundamentals": {"AAPL": row}}):
        result = api.get_financial_metrics("AAPL", "2024-03-31")

    assert [metric.model_dump() for metric in result] == [row]


def test_get_prices_kwarg_overrides_contextvar(monkeypatch) -> None:
    stale_row = price_row(close=90.0)
    fresh_row = price_row(close=120.0)
    monkeypatch.setattr(api, "_make_api_request", fail_request)

    with use_bundle({"prices": {"AAPL": [stale_row]}}):
        result = api.get_prices(
            "AAPL",
            "2024-01-01",
            "2024-01-02",
            evidence_bundle={"prices": {"AAPL": [fresh_row]}},
        )

    assert [price.model_dump() for price in result] == [fresh_row]


def test_kr_routing_passes_bundle_via_contextvar(monkeypatch) -> None:
    row = price_row()
    bundle = {"prices": {"005930": [row]}}
    captured = {}

    def fake_get_prices_kr(ticker, start_date, end_date, evidence_bundle=None):
        captured["ticker"] = ticker
        captured["evidence_bundle"] = evidence_bundle
        return [Price(**bundle["prices"][ticker][0])]

    monkeypatch.setattr(api_kr, "get_prices_kr", fake_get_prices_kr)

    with use_bundle(bundle):
        result = api.get_prices("005930", "2024-01-01", "2024-01-02", api_key=None)

    assert captured["ticker"] == "005930"
    assert captured["evidence_bundle"] is bundle
    assert [price.model_dump() for price in result] == [row]


def test_no_contextvar_no_bundle_falls_back_to_fetch(monkeypatch) -> None:
    row = price_row()
    calls = []
    patch_price_cache_miss(monkeypatch)

    def fake_request(*args, **kwargs):
        calls.append((args, kwargs))
        return response({"ticker": "AAPL", "prices": [row]})

    monkeypatch.setattr(api, "_make_api_request", fake_request)

    result = api.get_prices("AAPL", "2024-01-01", "2024-01-02")

    assert calls
    assert [price.model_dump() for price in result] == [row]

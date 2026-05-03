from unittest.mock import Mock

import pytest

from src.data.models import FinancialMetrics, Price
from src.tools import api


def price_row() -> dict:
    return {
        "open": 100.0,
        "close": 101.0,
        "high": 102.0,
        "low": 99.0,
        "volume": 1000,
        "time": "2024-01-02T00:00:00Z",
    }


def financial_metrics_row(ticker: str = "AAPL") -> dict:
    row = {field: None for field in FinancialMetrics.model_fields}
    row.update(
        {
            "ticker": ticker,
            "report_period": "2024-03-31",
            "period": "ttm",
            "currency": "USD",
            "market_cap": 1230000.0,
            "return_on_equity": 0.25,
        }
    )
    return row


def line_item_row() -> dict:
    return {
        "ticker": "AAPL",
        "report_period": "2024-03-31",
        "period": "ttm",
        "currency": "USD",
        "revenue": 100000.0,
    }


def insider_trade_row() -> dict:
    return {
        "ticker": "AAPL",
        "issuer": "Apple Inc.",
        "name": "Jane Doe",
        "title": "Director",
        "is_board_director": True,
        "transaction_date": "2024-01-02",
        "transaction_shares": 100.0,
        "transaction_price_per_share": 101.0,
        "transaction_value": 10100.0,
        "shares_owned_before_transaction": 1000.0,
        "shares_owned_after_transaction": 900.0,
        "security_title": "Common Stock",
        "filing_date": "2024-01-03",
    }


def company_news_row() -> dict:
    return {
        "ticker": "AAPL",
        "title": "Apple news",
        "author": "Reporter",
        "source": "Example",
        "date": "2024-01-02T00:00:00Z",
        "url": "https://example.com/aapl",
        "sentiment": "positive",
    }


def response(payload: dict) -> Mock:
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = payload
    return mock_response


def fail_request(*args, **kwargs):
    pytest.fail("network fetch should not be called")


def patch_price_cache_miss(monkeypatch):
    monkeypatch.setattr(api._cache, "get_prices", lambda cache_key: None)
    monkeypatch.setattr(api._cache, "set_prices", lambda cache_key, data: None)


def test_get_prices_with_evidence_bundle_skips_fetch(monkeypatch):
    row = price_row()
    bundle = {"prices": {"AAPL": [row]}}
    monkeypatch.setattr(api, "_make_api_request", fail_request)

    result = api.get_prices(
        "AAPL",
        "2024-01-01",
        "2024-01-02",
        evidence_bundle=bundle,
    )

    assert [price.model_dump() for price in result] == [row]


def test_get_prices_without_evidence_bundle_falls_back(monkeypatch):
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


def test_get_financial_metrics_with_bundle(monkeypatch):
    row = financial_metrics_row()
    bundle = {"fundamentals": {"AAPL": row}}
    monkeypatch.setattr(api, "_make_api_request", fail_request)

    result = api.get_financial_metrics(
        "AAPL",
        "2024-03-31",
        evidence_bundle=bundle,
    )

    assert [metric.model_dump() for metric in result] == [row]


def test_search_line_items_with_bundle(monkeypatch):
    row = line_item_row()
    bundle = {"line_items": {"AAPL": {"revenue": [row]}}}
    monkeypatch.setattr(api, "_make_api_request", fail_request)

    result = api.search_line_items(
        "AAPL",
        ["revenue"],
        "2024-03-31",
        evidence_bundle=bundle,
    )

    assert [line_item.model_dump() for line_item in result] == [row]


def test_get_insider_trades_with_bundle(monkeypatch):
    row = insider_trade_row()
    bundle = {"insider_trades": {"AAPL": [row]}}
    monkeypatch.setattr(api, "_make_api_request", fail_request)

    result = api.get_insider_trades(
        "AAPL",
        "2024-01-31",
        evidence_bundle=bundle,
    )

    assert [trade.model_dump() for trade in result] == [row]


def test_get_company_news_with_bundle(monkeypatch):
    row = company_news_row()
    bundle = {"company_news": {"AAPL": [row]}}
    monkeypatch.setattr(api, "_make_api_request", fail_request)

    result = api.get_company_news(
        "AAPL",
        "2024-01-31",
        evidence_bundle=bundle,
    )

    assert [news.model_dump() for news in result] == [row]


def test_get_market_cap_with_bundle(monkeypatch):
    bundle = {"market_cap": {"AAPL": {"2024-01-31": 1230000.0}}}
    monkeypatch.setattr(api, "_make_api_request", fail_request)

    result = api.get_market_cap(
        "AAPL",
        "2024-01-31",
        evidence_bundle=bundle,
    )

    assert result == 1230000.0


def test_kr_routing_with_bundle_passes_through(monkeypatch):
    bundle = {"prices": {"005930": [price_row()]}}
    captured = {}

    def fake_get_prices_kr(ticker, start_date, end_date, evidence_bundle=None):
        captured["ticker"] = ticker
        captured["evidence_bundle"] = evidence_bundle
        return [Price(**bundle["prices"][ticker][0])]

    monkeypatch.setattr("src.tools.api_kr.get_prices_kr", fake_get_prices_kr)

    result = api.get_prices(
        "005930",
        "2024-01-01",
        "2024-01-02",
        evidence_bundle=bundle,
    )

    assert captured["ticker"] == "005930"
    assert captured["evidence_bundle"] is bundle
    assert len(result) == 1


def test_bundle_missing_ticker_falls_through_to_fetch(monkeypatch):
    row = price_row()
    calls = []
    patch_price_cache_miss(monkeypatch)

    def fake_request(*args, **kwargs):
        calls.append((args, kwargs))
        return response({"ticker": "AAPL", "prices": [row]})

    monkeypatch.setattr(api, "_make_api_request", fake_request)

    result = api.get_prices(
        "AAPL",
        "2024-01-01",
        "2024-01-02",
        evidence_bundle={"prices": {"MSFT": [row]}},
    )

    assert calls
    assert [price.model_dump() for price in result] == [row]

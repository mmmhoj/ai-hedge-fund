import pandas as pd
import pytest

from src.tools.api_kr import get_market_cap_kr, get_prices_kr


def fail_pykrx(*args, **kwargs):
    pytest.fail("pykrx should not be called")


def test_get_prices_kr_returns_pykrx_ohlcv(monkeypatch):
    df = pd.DataFrame(
        {
            "시가": [71200, 70000],
            "고가": [72100, 71500],
            "저가": [70800, 69500],
            "종가": [71800, 71000],
            "거래량": [1100000, 1000000],
        },
        index=pd.to_datetime(["2026-04-02", "2026-04-01"]),
    )
    calls = []

    def fake_get_market_ohlcv_by_date(start_date, end_date, ticker):
        calls.append((start_date, end_date, ticker))
        return df

    monkeypatch.setattr(
        "pykrx.stock.get_market_ohlcv_by_date",
        fake_get_market_ohlcv_by_date,
    )

    prices = get_prices_kr("005930", "2026-04-01", "2026-04-02")

    assert calls == [("20260401", "20260402", "005930")]
    assert len(prices) == 2
    assert [price.time for price in prices] == [
        "2026-04-01T00:00:00Z",
        "2026-04-02T00:00:00Z",
    ]
    assert prices[0].open == 70000
    assert prices[0].close == 71000
    assert prices[0].high == 71500
    assert prices[0].low == 69500
    assert prices[0].volume == 1000000
    assert prices[1].open == 71200
    assert prices[1].close == 71800
    assert prices[1].high == 72100
    assert prices[1].low == 70800
    assert prices[1].volume == 1100000


def test_get_prices_kr_empty_df_returns_empty_list(monkeypatch):
    df = pd.DataFrame(columns=["시가", "고가", "저가", "종가", "거래량"])

    monkeypatch.setattr(
        "pykrx.stock.get_market_ohlcv_by_date",
        lambda *args, **kwargs: df,
    )

    assert get_prices_kr("005930", "2026-04-01", "2026-04-02") == []


def test_get_prices_kr_uses_evidence_bundle_when_attached(monkeypatch):
    bundle = {
        "prices": {
            "005930": [
                {
                    "open": 70000,
                    "close": 71000,
                    "high": 71500,
                    "low": 69500,
                    "volume": 1000000,
                    "time": "2026-04-01T00:00:00Z",
                }
            ]
        }
    }
    monkeypatch.setattr("pykrx.stock.get_market_ohlcv_by_date", fail_pykrx)

    prices = get_prices_kr(
        "005930",
        "2026-04-01",
        "2026-04-01",
        evidence_bundle=bundle,
    )

    assert [price.model_dump() for price in prices] == bundle["prices"]["005930"]


def test_get_market_cap_kr_returns_latest_market_cap(monkeypatch):
    df = pd.DataFrame(
        {"시가총액": [415000000000.0]},
        index=pd.to_datetime(["2026-04-01"]),
    )
    calls = []

    def fake_get_market_cap_by_date(start_date, end_date, ticker):
        calls.append((start_date, end_date, ticker))
        return df

    monkeypatch.setattr(
        "pykrx.stock.get_market_cap_by_date",
        fake_get_market_cap_by_date,
    )

    market_cap = get_market_cap_kr("005930", "2026-04-01")

    assert calls == [("20260322", "20260401", "005930")]
    assert market_cap == 415000000000.0
    assert isinstance(market_cap, float)


def test_get_market_cap_kr_empty_returns_none(monkeypatch):
    df = pd.DataFrame(columns=["시가총액"])

    monkeypatch.setattr(
        "pykrx.stock.get_market_cap_by_date",
        lambda *args, **kwargs: df,
    )

    assert get_market_cap_kr("005930", "2026-04-01") is None


def test_get_market_cap_kr_stale_data_returns_none(monkeypatch):
    df = pd.DataFrame(
        {"시가총액": [415000000000.0]},
        index=pd.to_datetime(["2026-03-25"]),
    )

    monkeypatch.setattr(
        "pykrx.stock.get_market_cap_by_date",
        lambda *args, **kwargs: df,
    )

    assert get_market_cap_kr("005930", "2026-04-01") is None


def test_get_market_cap_kr_uses_evidence_bundle_when_attached(monkeypatch):
    bundle = {"market_cap": {"005930": {"2026-04-01": 415000000000.0}}}
    monkeypatch.setattr("pykrx.stock.get_market_cap_by_date", fail_pykrx)

    market_cap = get_market_cap_kr("005930", "2026-04-01", evidence_bundle=bundle)

    assert market_cap == 415000000000.0

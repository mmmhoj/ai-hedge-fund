import datetime as dt
import json
from unittest.mock import Mock

import pytest

from src.data.models import FinancialMetrics
from src.tools import api_kr
from src.tools.kis_client import KisClient


@pytest.fixture(autouse=True)
def kis_env(monkeypatch):
    monkeypatch.setenv("KIS_APP_KEY", "test-app-key")
    monkeypatch.setenv("KIS_APP_SECRET", "test-app-secret")


def response(payload: dict, status_code: int = 200) -> Mock:
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.json.return_value = payload
    mock_response.text = json.dumps(payload)
    return mock_response


def financial_metrics_row(ticker: str = "005930") -> dict:
    row = {field: None for field in FinancialMetrics.model_fields}
    row.update(
        {
            "ticker": ticker,
            "report_period": "2024-12-31",
            "period": "annual",
            "currency": "KRW",
            "price_to_earnings_ratio": 12.5,
        }
    )
    return row


def test_kis_client_token_cached_on_repeated_calls(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    calls = []

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return response(
            {
                "access_token": "token-1",
                "token_type": "Bearer",
                "expires_in": 86400,
            }
        )

    monkeypatch.setattr("src.tools.kis_client.requests.post", fake_post)

    client = KisClient(app_key="abc123456789", app_secret="secret", use_sandbox=True)

    assert client.access_token() == "token-1"
    assert client.access_token() == "token-1"
    assert len(calls) == 1
    assert calls[0]["timeout"] == 30

    cache_path = tmp_path / ".cache" / "kis" / "token-abc12345.json"
    assert cache_path.exists()
    assert cache_path.stat().st_mode & 0o777 == 0o600


def test_kis_client_token_refresh_when_expired(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    client = KisClient(app_key="abc123456789", app_secret="secret", use_sandbox=True)
    cache_path = client._token_cache_path()
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(
        json.dumps(
            {
                "access_token": "expired-token",
                "expires_at": (
                    dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
                ).isoformat(),
            }
        ),
        encoding="utf-8",
    )

    calls = []

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return response(
            {
                "access_token": "fresh-token",
                "token_type": "Bearer",
                "expires_in": 86400,
            }
        )

    monkeypatch.setattr("src.tools.kis_client.requests.post", fake_post)

    assert client.access_token() == "fresh-token"
    assert len(calls) == 1


def test_get_financial_metrics_kr_aligns_4_ratio_endpoints(monkeypatch):
    calls = []

    def fake_get(self, path, *, tr_id, params):
        calls.append({"path": path, "tr_id": tr_id, "params": params})
        if path.endswith("/financial-ratio"):
            return {
                "output": [
                    {"stac_yymm": "202412", "per": "12.5", "pbr": "1.30"},
                    {"stac_yymm": "202312", "per": "10.0", "pbr": "1.10"},
                ]
            }
        if path.endswith("/profit-ratio"):
            return {
                "output": [
                    {"stac_yymm": "202412", "roe_val": "15.3", "roa_val": "8.2"},
                    {"stac_yymm": "202312", "roe_val": "11.1", "roa_val": "6.4"},
                ]
            }
        if path.endswith("/stability-ratio"):
            return {
                "output": [
                    {"stac_yymm": "202412", "crnt_rate": "172.0", "lblt_rate": "55.0"},
                    {"stac_yymm": "202312", "crnt_rate": "161.0", "lblt_rate": "60.0"},
                ]
            }
        if path.endswith("/growth-ratio"):
            return {
                "output": [
                    {"stac_yymm": "202412", "grs": "8.1", "ntin_inrt": "12.5"},
                    {"stac_yymm": "202312", "grs": "4.5", "ntin_inrt": "7.0"},
                ]
            }
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(api_kr.KisClient, "get", fake_get)

    metrics = api_kr.get_financial_metrics_kr(
        "005930",
        "2025-01-31",
        period="annual",
        limit=2,
    )

    assert len(metrics) == 2
    assert {call["tr_id"] for call in calls} == {
        "FHKST66430300",
        "FHKST66430400",
        "FHKST66430600",
        "FHKST66430800",
    }
    assert metrics[0].ticker == "005930"
    assert metrics[0].report_period == "2024-12-31"
    assert metrics[0].period == "annual"
    assert metrics[0].currency == "KRW"
    assert metrics[0].price_to_earnings_ratio == 12.5
    assert metrics[0].price_to_book_ratio == 1.3
    assert metrics[0].return_on_equity == pytest.approx(0.153)
    assert metrics[0].return_on_assets == pytest.approx(0.082)
    assert metrics[0].current_ratio == pytest.approx(1.72)
    assert metrics[0].debt_to_equity == pytest.approx(0.55)
    assert metrics[0].revenue_growth == pytest.approx(0.081)
    assert metrics[0].earnings_growth == pytest.approx(0.125)


def test_get_financial_metrics_kr_period_quarterly_uses_fid_div_cls_code_1(monkeypatch):
    calls = []

    def fake_get(self, path, *, tr_id, params):
        calls.append({"path": path, "params": params})
        return {"output": []}

    monkeypatch.setattr(api_kr.KisClient, "get", fake_get)

    assert api_kr.get_financial_metrics_kr(
        "005930",
        "2025-01-31",
        period="quarterly",
    ) == []
    assert calls
    assert all(call["params"]["fid_div_cls_code"] == "1" for call in calls)


def test_get_financial_metrics_kr_evidence_bundle_short_circuit(monkeypatch):
    class FailClient:
        def __init__(self, *args, **kwargs):
            pytest.fail("KisClient should not be instantiated")

    row = financial_metrics_row()
    monkeypatch.setattr(api_kr, "KisClient", FailClient)

    result = api_kr.get_financial_metrics_kr(
        "005930",
        "2024-12-31",
        period="annual",
        evidence_bundle={"fundamentals": {"005930": [row]}},
    )

    assert [metric.model_dump() for metric in result] == [row]


def test_search_line_items_kr_revenue_from_income_statement(monkeypatch):
    calls = []

    def fake_get(self, path, *, tr_id, params):
        calls.append({"path": path, "tr_id": tr_id, "params": params})
        assert path.endswith("/income-statement")
        return {
            "output": [
                {
                    "stac_yymm": "202412",
                    "sale_account": "300000",
                    "thtr_ntin": "50000",
                }
            ]
        }

    monkeypatch.setattr(api_kr.KisClient, "get", fake_get)

    rows = api_kr.search_line_items_kr(
        "005930",
        ["revenue"],
        "2025-01-31",
        period="annual",
        limit=1,
    )

    assert len(rows) == 1
    assert calls[0]["tr_id"] == "FHKST66430200"
    assert rows[0].ticker == "005930"
    assert rows[0].report_period == "2024-12-31"
    assert rows[0].period == "annual"
    assert rows[0].currency == "KRW"
    assert rows[0].revenue == 300000.0


def test_search_line_items_kr_total_assets_from_balance_sheet(monkeypatch):
    calls = []

    def fake_get(self, path, *, tr_id, params):
        calls.append({"path": path, "tr_id": tr_id, "params": params})
        assert path.endswith("/balance-sheet")
        return {
            "output": [
                {
                    "stac_yymm": "202412",
                    "total_aset": "1000000",
                    "total_lblt": "400000",
                }
            ]
        }

    monkeypatch.setattr(api_kr.KisClient, "get", fake_get)

    rows = api_kr.search_line_items_kr(
        "005930",
        ["total_assets"],
        "2025-01-31",
        period="annual",
        limit=1,
    )

    assert len(rows) == 1
    assert calls[0]["tr_id"] == "FHKST66430100"
    assert rows[0].total_assets == 1000000.0


def test_search_line_items_kr_unknown_line_item_skipped(monkeypatch):
    def fail_get(*args, **kwargs):
        pytest.fail("KisClient.get should not be called for unknown line items")

    monkeypatch.setattr(api_kr.KisClient, "get", fail_get)

    assert api_kr.search_line_items_kr(
        "005930",
        ["not_a_line_item"],
        "2025-01-31",
    ) == []


def test_search_line_items_kr_evidence_bundle_short_circuit(monkeypatch):
    class FailClient:
        def __init__(self, *args, **kwargs):
            pytest.fail("KisClient should not be instantiated")

    row = {
        "ticker": "005930",
        "report_period": "2024-12-31",
        "period": "annual",
        "currency": "KRW",
        "revenue": 300000.0,
    }
    monkeypatch.setattr(api_kr, "KisClient", FailClient)

    result = api_kr.search_line_items_kr(
        "005930",
        ["revenue"],
        "2024-12-31",
        period="annual",
        evidence_bundle={"line_items": {"005930": {"revenue": [row]}}},
    )

    assert [line_item.model_dump() for line_item in result] == [row]

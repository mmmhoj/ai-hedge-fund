import sys
import types

import pandas as pd
import pytest

from src.data.models import CompanyFacts, InsiderTrade
from src.tools.api_kr import get_company_facts_kr, get_insider_trades_kr


def dart_filing(
    report_name: str,
    *,
    corp_name: str = "Samsung",
    flr_nm: str = "Holder",
    date: str = "2026-05-01",
) -> dict:
    return {
        "corp_code": "00126380",
        "corp_name": corp_name,
        "stock_code": "005930",
        "corp_cls": "Y",
        "report_nm": report_name,
        "rcept_no": f"{date}-{flr_nm}",
        "flr_nm": flr_nm,
        "rcept_dt": date,
        "rm": "",
    }


def install_fake_dart(monkeypatch, *, list_df=None, company_result=None) -> dict:
    calls = {"init": [], "list": [], "company": []}

    class FakeOpenDartReader:
        def __init__(self, api_key):
            calls["init"].append(api_key)

        def list(self, corp, start, end, kind="A"):
            calls["list"].append((corp, start, end, kind))
            return list_df

        def company(self, corp):
            calls["company"].append(corp)
            if isinstance(company_result, Exception):
                raise company_result
            return company_result

    monkeypatch.setenv("DART_API_KEY", "test-dart-key")
    fake_module = types.SimpleNamespace(OpenDartReader=FakeOpenDartReader)
    monkeypatch.setitem(sys.modules, "OpenDartReader", fake_module)
    return calls


def test_get_insider_trades_kr_maps_majorstock_filings_to_insider_trade(monkeypatch):
    df = pd.DataFrame(
        [
            dart_filing(
                "주식등의대량보유상황보고서",
                corp_name="Samsung Electronics",
                flr_nm="Major Holder",
                date="2026-04-15",
            ),
            dart_filing(
                "임원·주요주주특정증권등소유상황보고서",
                corp_name="",
                flr_nm="Executive Holder",
                date="2026-04-20",
            ),
        ]
    )
    calls = install_fake_dart(monkeypatch, list_df=df, company_result={"corp_name": "Samsung"})

    trades = get_insider_trades_kr(
        "005930",
        "2026-05-01",
        start_date="2026-04-01",
        limit=10,
    )

    assert calls["init"] == ["test-dart-key"]
    assert calls["list"] == [("005930", "2026-04-01", "2026-05-01", "D")]
    assert calls["company"] == ["005930"]
    assert all(isinstance(trade, InsiderTrade) for trade in trades)
    assert [
        (
            trade.ticker,
            trade.issuer,
            trade.name,
            trade.transaction_date,
            trade.filing_date,
            trade.security_title,
        )
        for trade in trades
    ] == [
        (
            "005930",
            "Samsung Electronics",
            "Major Holder",
            "2026-04-15",
            "2026-04-15",
            "보통주",
        ),
        (
            "005930",
            "Samsung",
            "Executive Holder",
            "2026-04-20",
            "2026-04-20",
            "보통주",
        ),
    ]


def test_get_insider_trades_kr_filters_unrelated_filings(monkeypatch):
    df = pd.DataFrame(
        [
            dart_filing("주식등의대량보유상황보고서", flr_nm="Major Holder"),
            dart_filing("분기보고서", flr_nm="Quarterly Reporter"),
        ]
    )
    install_fake_dart(monkeypatch, list_df=df, company_result={"corp_name": "Samsung"})

    trades = get_insider_trades_kr(
        "005930",
        "2026-05-01",
        start_date="2026-04-01",
        limit=10,
    )

    assert len(trades) == 1
    assert trades[0].name == "Major Holder"


def test_get_insider_trades_kr_respects_limit(monkeypatch):
    df = pd.DataFrame(
        [
            dart_filing(
                "주식등의대량보유상황보고서",
                flr_nm=f"Holder {idx}",
                date=f"2026-04-{idx + 1:02d}",
            )
            for idx in range(5)
        ]
    )
    install_fake_dart(monkeypatch, list_df=df, company_result={"corp_name": "Samsung"})

    trades = get_insider_trades_kr(
        "005930",
        "2026-05-01",
        start_date="2026-04-01",
        limit=2,
    )

    assert len(trades) == 2
    assert [trade.name for trade in trades] == ["Holder 0", "Holder 1"]


def test_get_insider_trades_kr_empty_returns_empty_list(monkeypatch):
    df = pd.DataFrame(columns=list(dart_filing("주식등의대량보유상황보고서").keys()))
    install_fake_dart(monkeypatch, list_df=df, company_result={"corp_name": "Samsung"})

    assert get_insider_trades_kr("005930", "2026-05-01", start_date="2026-04-01") == []


def test_get_insider_trades_kr_evidence_bundle_short_circuit(monkeypatch):
    row = {
        "ticker": "005930",
        "issuer": "Samsung",
        "name": "Major Holder",
        "title": None,
        "is_board_director": None,
        "transaction_date": "2026-05-01",
        "transaction_shares": None,
        "transaction_price_per_share": None,
        "transaction_value": None,
        "shares_owned_before_transaction": None,
        "shares_owned_after_transaction": None,
        "security_title": "보통주",
        "filing_date": "2026-05-01",
    }

    class FailOpenDartReader:
        def __init__(self, api_key):
            pytest.fail("OpenDartReader should not be instantiated")

    fake_module = types.SimpleNamespace(OpenDartReader=FailOpenDartReader)
    monkeypatch.setitem(sys.modules, "OpenDartReader", fake_module)

    trades = get_insider_trades_kr(
        "005930",
        "2026-05-01",
        evidence_bundle={"insider_trades": {"005930": [row]}},
    )

    assert [trade.model_dump() for trade in trades] == [row]


def test_get_company_facts_kr_returns_company_metadata(monkeypatch):
    calls = install_fake_dart(
        monkeypatch,
        company_result={"corp_name": "Samsung Electronics", "corp_cls": "Y"},
    )

    facts = get_company_facts_kr("005930")

    assert calls["init"] == ["test-dart-key"]
    assert calls["company"] == ["005930"]
    assert isinstance(facts, CompanyFacts)
    assert facts.ticker == "005930"
    assert facts.name == "Samsung Electronics"
    assert facts.cik is None
    assert facts.industry is None


def test_get_company_facts_kr_handles_dart_failure(monkeypatch):
    install_fake_dart(monkeypatch, company_result=RuntimeError("DART unavailable"))

    assert get_company_facts_kr("005930") is None

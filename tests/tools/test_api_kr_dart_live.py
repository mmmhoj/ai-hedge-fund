import datetime as dt
import os

import pytest

from src.data.models import CompanyFacts
from src.tools.api_kr import get_company_facts_kr, get_insider_trades_kr

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE_TESTS") != "1",
        reason="set RUN_LIVE_TESTS=1 to run live DART tests",
    ),
    pytest.mark.skipif(
        not os.environ.get("DART_API_KEY"),
        reason="set DART_API_KEY to run live DART tests",
    ),
]


def fmt(day: dt.date) -> str:
    return day.strftime("%Y-%m-%d")


def test_get_insider_trades_kr_live():
    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=90)

    trades = get_insider_trades_kr(
        "005930",
        fmt(end_date),
        start_date=fmt(start_date),
    )

    assert isinstance(trades, list)


def test_get_company_facts_kr_live():
    facts = get_company_facts_kr("005930")

    assert isinstance(facts, CompanyFacts)
    assert facts.ticker == "005930"
    assert facts.name
    assert "삼성전자" in facts.name or "samsung" in facts.name.lower()

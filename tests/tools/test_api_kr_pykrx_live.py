import datetime as dt
import os

import pytest

from src.tools.api_kr import get_market_cap_kr, get_prices_kr

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE_TESTS") != "1",
        reason="set RUN_LIVE_TESTS=1 to run live pykrx tests",
    ),
]


def previous_weekday(day: dt.date | None = None) -> dt.date:
    current = day or dt.date.today()
    current -= dt.timedelta(days=1)
    while current.weekday() >= 5:
        current -= dt.timedelta(days=1)
    return current


def fmt(day: dt.date) -> str:
    return day.strftime("%Y-%m-%d")


def test_get_prices_kr_live():
    end_date = previous_weekday()
    start_date = end_date - dt.timedelta(days=10)

    prices = get_prices_kr("005930", fmt(start_date), fmt(end_date))

    assert prices
    assert all(price.open > 0 for price in prices)


def test_get_market_cap_kr_live():
    end_date = previous_weekday()

    assert get_market_cap_kr("005930", fmt(end_date)) > 0

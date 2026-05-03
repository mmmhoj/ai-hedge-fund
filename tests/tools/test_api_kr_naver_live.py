import datetime as dt
import logging
import os

import pytest

from src.tools.api_kr import get_company_news_kr

logger = logging.getLogger(__name__)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE_TESTS") != "1",
        reason="set RUN_LIVE_TESTS=1 to run live Naver Finance news tests",
    ),
]


def fmt(day: dt.date) -> str:
    return day.strftime("%Y-%m-%d")


def test_get_company_news_kr_live():
    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=7)

    news = get_company_news_kr("005930", fmt(end_date), start_date=fmt(start_date), limit=20)

    if not news:
        logger.info("Naver Finance news returned no rows; UA may be blocked or no recent ticker news")

    assert isinstance(news, list)

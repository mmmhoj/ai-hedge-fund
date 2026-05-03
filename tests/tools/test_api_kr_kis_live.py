import os
import time

import pytest

from src.tools.api_kr import get_financial_metrics_kr, search_line_items_kr

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE_TESTS") != "1",
        reason="set RUN_LIVE_TESTS=1 to run live KIS tests",
    ),
]


def test_get_financial_metrics_kr_live():
    metrics = get_financial_metrics_kr(
        "005930",
        "2026-05-03",
        period="annual",
        limit=1,
    )

    assert metrics
    row = metrics[0]
    assert row.ticker == "005930"
    assert row.currency == "KRW"
    assert any(
        getattr(row, field) is not None
        for field in (
            "return_on_equity",
            "operating_margin",
            "current_ratio",
            "debt_to_equity",
            "earnings_per_share",
        )
    )


def test_search_line_items_kr_live():
    time.sleep(1.5)
    rows = search_line_items_kr("005930", ["revenue", "net_income"], "2026-05-03", limit=1)

    assert rows

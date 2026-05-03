"""Korean market adapter for ai-hedge-fund.

Provides the same surface as `src.tools.api` (get_prices, get_financial_metrics,
search_line_items, get_insider_trades, get_company_news, get_market_cap,
get_company_facts) for Korean KOSPI/KOSDAQ tickers (6-digit numeric).

Data sources:
  - KIS Developers Open API: financial statements + pre-computed ratios
  - pykrx: OHLCV + market cap (faster than KIS for price data)
  - OpenDartReader: company facts + insider (major shareholder) filings
  - Naver Finance RSS: company news

All functions raise if required env vars are missing at call time. Skeleton
implementations raise NotImplementedError — to be filled in Step 2 after
KIS credentials are provisioned.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from src.data.models import (
    CompanyFacts,
    CompanyNews,
    FinancialMetrics,
    InsiderTrade,
    LineItem,
    Price,
)


@dataclass(frozen=True)
class KrCredentials:
    kis_app_key: str
    kis_app_secret: str
    kis_account: str | None
    dart_api_key: str

    @classmethod
    def from_env(cls) -> "KrCredentials":
        def require(name: str) -> str:
            value = os.environ.get(name)
            if not value:
                raise RuntimeError(f"Missing required env var: {name}")
            return value

        return cls(
            kis_app_key=require("KIS_APP_KEY"),
            kis_app_secret=require("KIS_APP_SECRET"),
            kis_account=os.environ.get("KIS_ACCOUNT"),
            dart_api_key=require("DART_API_KEY"),
        )


# ---------------------------------------------------------------------------
# KIS response -> FinancialMetrics field mapping (Step 2 will populate).
#
# Target: src/data/models.py :: FinancialMetrics has 60 fields. KIS supplies
# these via four endpoints (profit-ratio, stability-ratio, growth-ratio,
# financial-ratio) plus balance-sheet / income-statement for derived values.
#
# Mapping strategy:
#   - KIS `profit_ratio`       -> gross/operating/net_margin, ROE, ROA
#   - KIS `stability_ratio`    -> debt_to_equity, debt_to_assets, interest_coverage
#   - KIS `growth_ratio`       -> revenue_growth, earnings_growth, ...
#   - KIS `financial_ratio`    -> PER, PBR, EPS, BPS, payout_ratio, DIV
#   - pykrx (per_bps_by_date)  -> PER/PBR/EPS/BPS (daily, cross-check)
#   - Derived (our code)       -> EV/EBITDA, FCF_yield, PEG, ROIC, DSO, ...
# ---------------------------------------------------------------------------
KIS_FIELD_TO_METRIC: dict[str, str] = {
    # Populated in Step 2. Example entries:
    # "bsop_prfi_inrt":     "operating_income_growth",
    # "ntin_inrt":          "earnings_growth",
    # "roe_val":            "return_on_equity",
    # "per":                "price_to_earnings_ratio",
    # "pbr":                "price_to_book_ratio",
}


# ---------------------------------------------------------------------------
# line_item -> (KIS endpoint, KIS column) mapping for search_line_items_kr.
# Each ai-hedge-fund persona requests a subset. Dict key is the English
# line-item name used in src/agents/*.py; value is (endpoint, column).
# ---------------------------------------------------------------------------
LINE_ITEM_SOURCE: dict[str, tuple[str, str]] = {
    # Populated in Step 2. Example entries:
    # "revenue":            ("income_statement", "sale_account"),
    # "net_income":         ("income_statement", "thtr_ntin"),
    # "operating_income":   ("income_statement", "bsop_prti"),
    # "total_assets":       ("balance_sheet",    "total_aset"),
    # "shareholders_equity":("balance_sheet",    "total_cptl"),
    # ...
}


def get_prices_kr(ticker: str, start_date: str, end_date: str) -> list[Price]:
    """OHLCV history via pykrx (no KIS auth needed, no rate limit)."""
    raise NotImplementedError("Step 2: implement via pykrx.get_market_ohlcv_by_date")


def get_market_cap_kr(ticker: str, end_date: str) -> float | None:
    """Market cap as of end_date via pykrx."""
    raise NotImplementedError("Step 2: implement via pykrx.get_market_cap_by_date")


def get_company_facts_kr(ticker: str) -> CompanyFacts | None:
    """Company metadata via DART OpenDartReader."""
    raise NotImplementedError("Step 2: implement via OpenDartReader.company")


def get_financial_metrics_kr(
    ticker: str,
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
) -> list[FinancialMetrics]:
    """60-metric list for Korean ticker.

    Assembles by calling KIS profit/stability/growth/financial ratio endpoints
    in parallel, aligning report_period across responses, computing derived
    metrics (EV/EBITDA, FCF_yield, PEG, ROIC, DSO, ...), and collapsing
    quarterly rows to TTM when period == "ttm".
    """
    raise NotImplementedError("Step 2: assemble from KIS 4 ratio endpoints + derived")


def search_line_items_kr(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
) -> list[LineItem]:
    """Dynamic line-item search over KIS balance-sheet + income-statement.

    Looks up each requested name in LINE_ITEM_SOURCE, fetches the parent
    endpoint once per (ticker, period), and returns LineItem rows (one per
    reporting period) with the requested subset attached via dynamic fields.
    """
    raise NotImplementedError("Step 2: map requested names via LINE_ITEM_SOURCE")


def get_insider_trades_kr(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
) -> list[InsiderTrade]:
    """Major-shareholder reports (5% rule) from DART.

    Note: Korean reporting semantics differ from US insider trades. We map
    DART `majorstock` / `elestock` filings into the InsiderTrade schema with
    a best-effort shape — transaction details may be partial.
    """
    raise NotImplementedError("Step 2: implement via OpenDartReader major-stock filings")


def get_company_news_kr(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 100,
) -> list[CompanyNews]:
    """Company news via Naver Finance RSS (unauthenticated)."""
    raise NotImplementedError("Step 2: scrape Naver Finance RSS for ticker")

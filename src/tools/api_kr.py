"""Korean market adapter for ai-hedge-fund.

Provides the same surface as `src.tools.api` (get_prices, get_financial_metrics,
search_line_items, get_insider_trades, get_company_news, get_market_cap,
get_company_facts) for Korean KOSPI/KOSDAQ tickers (6-digit numeric).

Data sources:
  - KIS Developers Open API: financial statements + pre-computed ratios
  - pykrx: OHLCV + market cap (faster than KIS for price data)
  - OpenDartReader: company facts + insider (major shareholder) filings
  - Naver Finance: company news
"""
from __future__ import annotations

import calendar
import datetime as dt
import logging
import os
from dataclasses import dataclass
from typing import Any

from src.data.models import (
    CompanyFacts,
    CompanyNews,
    FinancialMetrics,
    InsiderTrade,
    LineItem,
    Price,
)
from src.tools.kis_client import KisClient

logger = logging.getLogger(__name__)


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


def _dart_reader() -> Any | None:
    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        logger.warning("Missing DART_API_KEY; cannot fetch DART data")
        return None

    try:
        import OpenDartReader

        reader_factory = getattr(OpenDartReader, "OpenDartReader", OpenDartReader)
        return reader_factory(api_key)
    except Exception as e:
        logger.warning("Failed to initialize OpenDartReader: %s", e)
        return None


def _clean_dart_value(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return None
    return text


def _is_dart_ownership_report(report_name: str) -> bool:
    normalized_report_name = report_name.replace("ㆍ", "·")
    return (
        "주식등의대량보유상황보고서" in normalized_report_name
        or "임원·주요주주특정증권" in normalized_report_name
    )


KIS_RATIO_ENDPOINTS: dict[str, tuple[str, str]] = {
    "financial_ratio": (
        "/uapi/domestic-stock/v1/finance/financial-ratio",
        "FHKST66430300",
    ),
    "profit_ratio": (
        "/uapi/domestic-stock/v1/finance/profit-ratio",
        "FHKST66430400",
    ),
    "stability_ratio": (
        "/uapi/domestic-stock/v1/finance/stability-ratio",
        "FHKST66430600",
    ),
    "growth_ratio": (
        "/uapi/domestic-stock/v1/finance/growth-ratio",
        "FHKST66430800",
    ),
}

KIS_RATIO_METRIC_SOURCE: dict[str, tuple[str, tuple[str, ...], bool]] = {
    "price_to_earnings_ratio": (
        "financial_ratio",
        ("price_to_earnings_ratio", "per", "prpr_epr"),
        False,
    ),
    "price_to_book_ratio": ("financial_ratio", ("price_to_book_ratio", "pbr"), False),
    "price_to_sales_ratio": ("financial_ratio", ("price_to_sales_ratio", "psr"), False),
    "gross_margin": ("profit_ratio", ("gross_margin", "grs_margin", "grs"), True),
    "operating_margin": ("profit_ratio", ("operating_margin", "bsop_prfi_inrt"), True),
    "net_margin": ("profit_ratio", ("net_margin", "ntin_inrt"), True),
    "return_on_equity": ("profit_ratio", ("return_on_equity", "roe_val", "roe"), True),
    "return_on_assets": ("profit_ratio", ("return_on_assets", "roa_val", "roa"), True),
    "current_ratio": ("stability_ratio", ("current_ratio", "crnt_rate", "cur_rate"), True),
    "quick_ratio": ("stability_ratio", ("quick_ratio", "quick_rate"), True),
    "cash_ratio": ("stability_ratio", ("cash_ratio", "cash_rate"), True),
    "debt_to_equity": (
        "stability_ratio",
        ("debt_to_equity", "lblt_rate", "liabilitytoequity"),
        True,
    ),
    "debt_to_assets": ("stability_ratio", ("debt_to_assets", "debt_aset_rate"), True),
    "interest_coverage": (
        "stability_ratio",
        ("interest_coverage", "int_cvrg", "intr_cvrg"),
        False,
    ),
    "revenue_growth": ("growth_ratio", ("revenue_growth", "grs"), True),
    "earnings_growth": ("growth_ratio", ("earnings_growth", "ntin_inrt"), True),
    "book_value_growth": ("growth_ratio", ("book_value_growth", "bps_inrt"), True),
    "earnings_per_share_growth": ("growth_ratio", ("earnings_per_share_growth", "eps_inrt"), True),
    "operating_income_growth": ("growth_ratio", ("operating_income_growth", "bsop_prfi_inrt"), True),
    "payout_ratio": ("financial_ratio", ("payout_ratio", "payout_rate", "dvpr"), True),
    "earnings_per_share": ("financial_ratio", ("earnings_per_share", "eps"), False),
    "book_value_per_share": ("financial_ratio", ("book_value_per_share", "bps"), False),
}

KIS_STATEMENT_ENDPOINTS: dict[str, tuple[str, str]] = {
    "balance_sheet": (
        "/uapi/domestic-stock/v1/finance/balance-sheet",
        "FHKST66430100",
    ),
    "income_statement": (
        "/uapi/domestic-stock/v1/finance/income-statement",
        "FHKST66430200",
    ),
}

LINE_ITEM_SOURCE: dict[str, tuple[str, str]] = {
    "revenue": ("income_statement", "sale_account"),
    "net_income": ("income_statement", "thtr_ntin"),
    "operating_income": ("income_statement", "bsop_prti"),
    "gross_profit": ("income_statement", "grs_prfi"),
    "total_assets": ("balance_sheet", "total_aset"),
    "total_liabilities": ("balance_sheet", "total_lblt"),
    "shareholders_equity": ("balance_sheet", "total_cptl"),
    "cash_and_equivalents": ("balance_sheet", "cash_equivalents"),
    "total_debt": ("balance_sheet", "total_debt"),
    "capital_expenditure": ("income_statement", "cptl_expn"),
    "depreciation_and_amortization": ("income_statement", "depr_amrt"),
}

LINE_ITEM_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("sale_account", "revenue", "sale_amt"),
    "net_income": ("thtr_ntin", "net_income", "cup_nga"),
    "operating_income": ("bsop_prti", "bsop_prfi", "operating_income", "bus_pro"),
    "gross_profit": ("grs_prfi", "gross_profit", "sale_grs_prfi"),
    "total_assets": ("total_aset", "total_assets"),
    "total_liabilities": ("total_lblt", "total_liabilities"),
    "shareholders_equity": ("total_cptl", "shareholders_equity"),
    "cash_and_equivalents": (
        "cash_equivalents",
        "cash_and_equivalents",
        "cash_and_cash_equivalents",
        "cash_eqvl",
    ),
    "total_debt": ("total_debt", "debt", "borrowings", "total_lblt"),
    "capital_expenditure": ("cptl_expn", "capital_expenditure", "capex", "capx"),
    "depreciation_and_amortization": (
        "depr_amrt",
        "depreciation_and_amortization",
        "depreciation_amortization",
    ),
}


def get_prices_kr(
    ticker: str,
    start_date: str,
    end_date: str,
    evidence_bundle: dict | None = None,
) -> list[Price]:
    """OHLCV history via pykrx (no KIS auth needed, no rate limit)."""
    if evidence_bundle is not None:
        bundle_prices = evidence_bundle.get("prices", {})
        if ticker in bundle_prices:
            return [Price(**row) for row in bundle_prices[ticker]]

    try:
        from pykrx import stock

        start_yyyymmdd = start_date.replace("-", "")
        end_yyyymmdd = end_date.replace("-", "")
        df = stock.get_market_ohlcv_by_date(start_yyyymmdd, end_yyyymmdd, ticker)
        if df.empty:
            return []

        prices = []
        for trading_date, row in df.sort_index().iterrows():
            prices.append(
                Price(
                    open=float(row["시가"]),
                    close=float(row["종가"]),
                    high=float(row["고가"]),
                    low=float(row["저가"]),
                    volume=int(row["거래량"]),
                    time=trading_date.strftime("%Y-%m-%dT00:00:00Z"),
                )
            )
        return prices
    except Exception as e:
        logger.warning("Failed to fetch pykrx OHLCV for %s: %s", ticker, e)
        return []


def get_market_cap_kr(
    ticker: str,
    end_date: str,
    evidence_bundle: dict | None = None,
) -> float | None:
    """Market cap as of end_date via pykrx."""
    if evidence_bundle is not None:
        bundle_market_caps = evidence_bundle.get("market_cap", {})
        if ticker in bundle_market_caps:
            return bundle_market_caps[ticker].get(end_date)

    try:
        from pykrx import stock

        requested_date = dt.datetime.strptime(end_date, "%Y-%m-%d").date()
        start_yyyymmdd = (requested_date - dt.timedelta(days=10)).strftime("%Y%m%d")
        end_yyyymmdd = requested_date.strftime("%Y%m%d")
        df = stock.get_market_cap_by_date(start_yyyymmdd, end_yyyymmdd, ticker)
        if df.empty:
            return None

        df = df.sort_index()
        latest_date = df.index[-1].date()
        if (requested_date - latest_date).days > 5:
            return None

        return float(df.iloc[-1]["시가총액"])
    except Exception as e:
        logger.warning("Failed to fetch pykrx market cap for %s: %s", ticker, e)
        return None


def get_company_facts_kr(ticker: str) -> CompanyFacts | None:
    """Company metadata via DART OpenDartReader."""
    dart = _dart_reader()
    if dart is None:
        return None

    try:
        company = dart.company(ticker)
        if company is None:
            return None

        name = _clean_dart_value(company.get("corp_name"))
        if name is None:
            return None

        return CompanyFacts(ticker=ticker, name=name, cik=None, industry=None)
    except Exception as e:
        logger.warning("Failed to fetch DART company facts for %s: %s", ticker, e)
        return None


def get_financial_metrics_kr(
    ticker: str,
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    evidence_bundle: dict | None = None,
) -> list[FinancialMetrics]:
    """60-metric list for Korean ticker via KIS 4 ratio endpoints."""
    if evidence_bundle is not None:
        bundle_fundamentals = evidence_bundle.get("fundamentals", {})
        if ticker in bundle_fundamentals:
            financial_metrics = bundle_fundamentals[ticker]
            if isinstance(financial_metrics, list):
                return [FinancialMetrics(**row) for row in financial_metrics[:limit]]
            return [FinancialMetrics(**financial_metrics)]

    try:
        client = KisClient()
        params = _kis_finance_params(ticker, period)
        responses_by_endpoint = {
            name: _rows_by_period(client.get(path, tr_id=tr_id, params=params))
            for name, (path, tr_id) in KIS_RATIO_ENDPOINTS.items()
        }

        period_keys = sorted(
            {
                period_key
                for endpoint_rows in responses_by_endpoint.values()
                for period_key in endpoint_rows
                if _is_period_lte(period_key, end_date)
            },
            key=_period_sort_key,
            reverse=True,
        )
        if not period_keys:
            return []

        metrics = []
        for period_key in period_keys[:limit]:
            row = {field: None for field in FinancialMetrics.model_fields}
            row.update(
                ticker=ticker,
                report_period=_format_report_period(period_key),
                period=period,
                currency="KRW",
            )
            endpoint_rows = {
                name: rows[period_key]
                for name, rows in responses_by_endpoint.items()
                if period_key in rows
            }
            for metric_name, (source, aliases, is_percent) in KIS_RATIO_METRIC_SOURCE.items():
                row[metric_name] = _metric_value(
                    endpoint_rows,
                    source=source,
                    aliases=aliases,
                    metric_name=metric_name,
                    is_percent=is_percent,
                )
            metrics.append(FinancialMetrics(**row))
        return metrics
    except Exception as e:
        logger.warning("Failed to fetch KIS financial metrics for %s: %s", ticker, e)
        return []


def search_line_items_kr(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    evidence_bundle: dict | None = None,
) -> list[LineItem]:
    """Dynamic line-item search over KIS balance-sheet + income-statement."""
    if evidence_bundle is not None:
        bundle_line_items = evidence_bundle.get("line_items", {})
        if ticker in bundle_line_items:
            ticker_line_items = bundle_line_items[ticker]
            rows_by_key: dict[tuple, dict] = {}
            ordered_keys: list[tuple] = []
            for line_item in line_items:
                for row in ticker_line_items.get(line_item, []):
                    row_key = (
                        row.get("ticker"),
                        row.get("report_period"),
                        row.get("period"),
                        row.get("currency"),
                    )
                    if row_key not in rows_by_key:
                        rows_by_key[row_key] = row.copy()
                        ordered_keys.append(row_key)
                    else:
                        rows_by_key[row_key].update(row)
            rows = [rows_by_key[row_key] for row_key in ordered_keys]
            return [LineItem(**row) for row in rows[:limit]]

    requested_sources = {
        line_item: LINE_ITEM_SOURCE[line_item]
        for line_item in line_items
        if line_item in LINE_ITEM_SOURCE
    }
    if not requested_sources:
        return []

    try:
        client = KisClient()
        params = _kis_finance_params(ticker, period)
        statement_types = {statement_type for statement_type, _ in requested_sources.values()}
        responses_by_statement = {
            statement_type: _rows_by_period(client.get(path, tr_id=tr_id, params=params))
            for statement_type, (path, tr_id) in KIS_STATEMENT_ENDPOINTS.items()
            if statement_type in statement_types
        }

        period_keys = sorted(
            {
                period_key
                for statement_rows in responses_by_statement.values()
                for period_key in statement_rows
                if _is_period_lte(period_key, end_date)
            },
            key=_period_sort_key,
            reverse=True,
        )
        if not period_keys:
            return []

        rows = []
        base_fields = {"ticker", "report_period", "period", "currency"}
        for period_key in period_keys:
            row = {
                "ticker": ticker,
                "report_period": _format_report_period(period_key),
                "period": period,
                "currency": "KRW",
            }
            for line_item, (statement_type, field_name) in requested_sources.items():
                statement_row = responses_by_statement.get(statement_type, {}).get(period_key, {})
                value = _line_item_value(statement_row, line_item, field_name)
                if value is not None:
                    row[line_item] = value
            if set(row) - base_fields:
                rows.append(row)
            if len(rows) >= limit:
                break

        return [LineItem(**row) for row in rows]
    except Exception as e:
        logger.warning("Failed to fetch KIS line items for %s: %s", ticker, e)
        return []


def get_insider_trades_kr(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    evidence_bundle: dict | None = None,
) -> list[InsiderTrade]:
    """Major-shareholder reports (5% rule) from DART.

    Note: Korean reporting semantics differ from US insider trades. Maps
    DART majorstock + executive holding filings to InsiderTrade with
    best-effort field shape.
    """
    if evidence_bundle is not None:
        bundle_trades = evidence_bundle.get("insider_trades", {})
        if ticker in bundle_trades:
            return [InsiderTrade(**row) for row in bundle_trades[ticker]]

    dart = _dart_reader()
    if dart is None:
        return []

    try:
        filings = dart.list(ticker, start_date or "2020-01-01", end_date, kind="D")
        if filings is None or getattr(filings, "empty", False):
            return []

        trades: list[InsiderTrade] = []
        issuer_fallback: str | None = None
        for _, filing in filings.iterrows():
            report_name = _clean_dart_value(filing.get("report_nm")) or ""
            if not _is_dart_ownership_report(report_name):
                continue

            issuer = _clean_dart_value(filing.get("corp_name"))
            if issuer is None:
                if issuer_fallback is None:
                    company = dart.company(ticker)
                    issuer_fallback = _clean_dart_value(company.get("corp_name"))
                issuer = issuer_fallback

            receipt_date = _clean_dart_value(filing.get("rcept_dt")) or end_date
            trades.append(
                InsiderTrade(
                    ticker=ticker,
                    issuer=issuer,
                    name=_clean_dart_value(filing.get("flr_nm")),
                    title=None,
                    is_board_director=None,
                    transaction_date=receipt_date,
                    transaction_shares=None,
                    transaction_price_per_share=None,
                    transaction_value=None,
                    shares_owned_before_transaction=None,
                    shares_owned_after_transaction=None,
                    security_title="보통주",
                    filing_date=receipt_date,
                )
            )
            if len(trades) >= limit:
                break
        return trades
    except Exception as e:
        logger.warning("Failed to fetch DART insider trades for %s: %s", ticker, e)
        return []


def get_company_news_kr(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 100,
    evidence_bundle: dict | None = None,
) -> list[CompanyNews]:
    """Company news via Naver Finance news listing (unauthenticated)."""
    if evidence_bundle is not None:
        bundle_news = evidence_bundle.get("company_news", {})
        if ticker in bundle_news:
            return [CompanyNews(**row) for row in bundle_news[ticker]]

    if limit <= 0:
        return []

    try:
        from urllib.parse import urljoin

        import requests
        from bs4 import BeautifulSoup

        kst = dt.timezone(dt.timedelta(hours=9))
        end_bound = dt.datetime.strptime(end_date[:10], "%Y-%m-%d").date()
        start_bound = (
            dt.datetime.strptime(start_date[:10], "%Y-%m-%d").date() if start_date else None
        )
        if start_bound and start_bound > end_bound:
            return []

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
        }
        news: list[CompanyNews] = []

        for page in range(1, 11):
            url = (
                "https://finance.naver.com/item/news_news.naver?"
                f"code={ticker}&page={page}&sm=title_entity_id.basic&clusterId="
            )
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                logger.warning(
                    "Failed to fetch Naver Finance news for %s: HTTP %s",
                    ticker,
                    response.status_code,
                )
                return []

            content = getattr(response, "content", None)
            html = (
                content
                if isinstance(content, (bytes, bytearray)) and content
                else getattr(response, "text", "")
            )
            soup = BeautifulSoup(html, "html.parser")

            rows = soup.select('table[summary="종목뉴스"] tr')
            page_dates: list[dt.date] = []
            page_had_articles = False

            for row in rows:
                title_link = row.select_one("td.title a")
                date_cell = row.select_one("td.date")
                if not title_link or not date_cell:
                    continue

                date_text = date_cell.get_text(" ", strip=True)
                try:
                    article_dt = dt.datetime.strptime(date_text, "%Y.%m.%d %H:%M")
                except ValueError:
                    continue

                page_had_articles = True
                article_date = article_dt.date()
                page_dates.append(article_date)

                if start_bound and article_date < start_bound:
                    continue
                if article_date > end_bound:
                    continue

                title = (title_link.get("title") or title_link.get_text(" ", strip=True)).strip()
                href = title_link.get("href")
                if not title or not href:
                    continue

                source_cell = row.select_one("td.info")
                source = source_cell.get_text(" ", strip=True) if source_cell else "Naver Finance"

                news.append(
                    CompanyNews(
                        ticker=ticker,
                        title=title,
                        author=None,
                        source=source,
                        date=article_dt.replace(tzinfo=kst).isoformat(),
                        url=urljoin("https://finance.naver.com", href),
                        sentiment=None,
                    )
                )
                if len(news) >= limit:
                    return news[:limit]

            if not page_had_articles:
                break
            if start_bound and page_dates and min(page_dates) < start_bound:
                break

        return news[:limit]
    except Exception as e:
        logger.warning("Failed to scrape Naver Finance news for %s: %s", ticker, e)
        return []


def _kis_finance_params(ticker: str, period: str) -> dict[str, str]:
    return {
        "fid_div_cls_code": "1" if period.lower() == "quarterly" else "0",
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": ticker,
    }


def _response_rows(data: dict) -> list[dict]:
    output = data.get("output", [])
    if isinstance(output, dict):
        return [output]
    if not isinstance(output, list):
        return []
    return [row for row in output if isinstance(row, dict)]


def _rows_by_period(data: dict) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for row in _response_rows(data):
        period_key = _period_key(row)
        if period_key:
            rows[period_key] = row
    return rows


def _period_key(row: dict) -> str | None:
    value = row.get("stac_yymm")
    if value is None:
        return None
    period_key = str(value).strip()
    return period_key or None


def _metric_value(
    endpoint_rows: dict[str, dict],
    *,
    source: str,
    aliases: tuple[str, ...],
    metric_name: str,
    is_percent: bool,
) -> float | None:
    search_order = [source] + [name for name in endpoint_rows if name != source]
    for endpoint_name in search_order:
        value, alias = _first_present(endpoint_rows.get(endpoint_name, {}), aliases)
        if alias is not None:
            return _to_metric_float(value, alias, metric_name, is_percent)
    return None


def _line_item_value(row: dict, line_item: str, field_name: str) -> float | None:
    aliases = (field_name,) + LINE_ITEM_FIELD_ALIASES.get(line_item, ())
    value, _ = _first_present(row, aliases)
    return _to_float(value)


def _first_present(row: dict, aliases: tuple[str, ...]) -> tuple[object | None, str | None]:
    for alias in aliases:
        if alias in row and row[alias] not in (None, ""):
            return row[alias], alias
    return None, None


def _to_metric_float(
    value: object,
    alias: str,
    metric_name: str,
    is_percent: bool,
) -> float | None:
    number = _to_float(value)
    if number is None:
        return None
    if not is_percent:
        return number
    if alias == metric_name or abs(number) <= 1:
        return number
    return number / 100


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None

    text = value.strip().replace(",", "").replace("%", "")
    if text in {"", "-", "--", "N/A", "n/a", "nan", "NaN"}:
        return None
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"

    try:
        return float(text)
    except ValueError:
        return None


def _is_period_lte(period_key: str, end_date: str) -> bool:
    period_date = _period_date(period_key)
    if period_date is None:
        return True
    try:
        requested_end_date = dt.datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        return True
    return period_date <= requested_end_date


def _period_sort_key(period_key: str) -> dt.date:
    return _period_date(period_key) or dt.date.min


def _format_report_period(period_key: str) -> str:
    period_date = _period_date(period_key)
    if period_date is None:
        return period_key
    return period_date.isoformat()


def _period_date(period_key: str) -> dt.date | None:
    digits = "".join(char for char in str(period_key) if char.isdigit())
    try:
        if len(digits) >= 8:
            return dt.datetime.strptime(digits[:8], "%Y%m%d").date()
        if len(digits) >= 6:
            year = int(digits[:4])
            month = int(digits[4:6])
            day = calendar.monthrange(year, month)[1]
            return dt.date(year, month, day)
    except ValueError:
        return None
    return None

"""Financial Datasets API client."""

from __future__ import annotations

import logging
import os
import time

import requests

from v2.data.models import (
    CompanyFacts,
    CompanyNews,
    Earnings,
    EarningsRecord,
    FinancialMetrics,
    InsiderTrade,
    Price,
)

logger = logging.getLogger(__name__)


class FDClient:
    """Financial Datasets API client.

    Usage::

        with FDClient() as fd:
            prices = fd.get_prices("AAPL", "2024-01-01", "2024-12-31")
    """

    BASE_URL = "https://api.financialdatasets.ai"
    _RETRY_DELAYS = (5, 15, 30)

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
        openbb_api_base: str | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("FINANCIAL_DATASETS_API_KEY", "")
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers["X-API-Key"] = self._api_key
        openbb_fallback_enabled = os.environ.get("OPENBB_PRICE_FALLBACK", "1").lower() not in {"0", "false", "no"}
        fallback_base = openbb_api_base if openbb_api_base is not None else os.environ.get("OPENBB_API_BASE", "http://127.0.0.1:6900/api/v1")
        self._openbb_api_base = fallback_base.rstrip("/") if openbb_fallback_enabled and fallback_base else ""
        self._openbb_price_provider = os.environ.get("OPENBB_PRICE_PROVIDER", "yfinance")

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> FDClient:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def close(self) -> None:
        """Close the HTTP session."""
        self._session.close()

    # ------------------------------------------------------------------
    # Prices
    # ------------------------------------------------------------------

    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        interval: str = "day",
        interval_multiplier: int = 1,
    ) -> list[Price]:
        """Fetch OHLC price bars."""
        data = self._get(
            "/prices/",
            {
                "ticker": ticker,
                "interval": interval,
                "interval_multiplier": interval_multiplier,
                "start_date": start_date,
                "end_date": end_date,
            },
            response_key="prices",
        )
        if not data:
            data = self._get_openbb_prices(
                ticker,
                start_date,
                end_date,
                interval=interval,
                interval_multiplier=interval_multiplier,
            )
        return [Price(**row) for row in data] if data else []

    # ------------------------------------------------------------------
    # Financial Metrics
    # ------------------------------------------------------------------

    def get_financial_metrics(
        self,
        ticker: str,
        end_date: str,
        period: str = "ttm",
        limit: int = 10,
    ) -> list[FinancialMetrics]:
        """Fetch financial metrics up to *end_date*."""
        data = self._get("/financial-metrics/", {
            "ticker": ticker,
            "report_period_lte": end_date,
            "period": period,
            "limit": limit,
        }, response_key="financial_metrics")
        return [FinancialMetrics(**row) for row in data] if data else []

    # ------------------------------------------------------------------
    # News
    # ------------------------------------------------------------------

    def get_news(
        self,
        ticker: str,
        end_date: str,
        start_date: str | None = None,
        limit: int = 1000,
    ) -> list[CompanyNews]:
        """Fetch company news."""
        params: dict = {"ticker": ticker, "end_date": end_date, "limit": limit}
        if start_date is not None:
            params["start_date"] = start_date
        data = self._get("/news/", params, response_key="news")
        return [CompanyNews(**row) for row in data] if data else []

    # ------------------------------------------------------------------
    # Insider Trades
    # ------------------------------------------------------------------

    def get_insider_trades(
        self,
        ticker: str,
        end_date: str,
        start_date: str | None = None,
        limit: int = 1000,
    ) -> list[InsiderTrade]:
        """Fetch insider trades."""
        params: dict = {"ticker": ticker, "filing_date_lte": end_date, "limit": limit}
        if start_date is not None:
            params["filing_date_gte"] = start_date
        data = self._get("/insider-trades/", params, response_key="insider_trades")
        return [InsiderTrade(**row) for row in data] if data else []

    # ------------------------------------------------------------------
    # Company Facts
    # ------------------------------------------------------------------

    def get_company_facts(self, ticker: str) -> CompanyFacts | None:
        """Fetch company metadata (single record)."""
        resp = self._request("GET", "/company/facts/", params={"ticker": ticker})
        if resp is None:
            return None
        facts_data = resp.json().get("company_facts")
        return CompanyFacts(**facts_data) if facts_data else None

    # ------------------------------------------------------------------
    # Earnings
    # ------------------------------------------------------------------

    def get_earnings(self, ticker: str) -> Earnings | None:
        """Fetch latest earnings for a single ticker."""
        data = self._get("/earnings/", {"ticker": ticker}, response_key="earnings")
        if not data:
            return None
        row = data[0] if isinstance(data, list) else data
        return Earnings(**row)

    def get_earnings_history(
        self,
        ticker: str,
        limit: int = 12,
    ) -> list[EarningsRecord]:
        """Fetch historical earnings filings as a flat list.

        Returns one record per SEC filing (8-K, 10-Q, 10-K, 20-F).
        The same ``report_period`` may appear multiple times with
        different ``source_type`` values.
        """
        data = self._get("/earnings/", {
            "ticker": ticker,
            "limit": limit,
        }, response_key="earnings")
        return [EarningsRecord(**row) for row in data] if data else []

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def get_market_cap(self, ticker: str, end_date: str) -> float | None:
        """Return market cap from company facts or financial metrics."""
        facts = self.get_company_facts(ticker)
        if facts is not None and facts.market_cap is not None:
            return facts.market_cap
        metrics = self.get_financial_metrics(ticker, end_date, limit=1)
        if metrics and metrics[0].market_cap is not None:
            return metrics[0].market_cap
        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get(
        self,
        path: str,
        params: dict,
        response_key: str,
    ) -> list[dict] | None:
        """GET and extract *response_key* from the JSON payload."""
        resp = self._request("GET", path, params=params)
        if resp is None:
            return None
        return resp.json().get(response_key)

    def _get_openbb_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        *,
        interval: str,
        interval_multiplier: int,
    ) -> list[dict] | None:
        """Fetch daily prices from local OpenBB when FD price coverage is unavailable."""
        if not self._openbb_api_base:
            return None
        if interval != "day" or interval_multiplier != 1:
            logger.warning(
                "OpenBB price fallback only supports daily bars; got %sx%s",
                interval_multiplier,
                interval,
            )
            return None

        try:
            resp = requests.get(
                f"{self._openbb_api_base}/equity/price/historical",
                params={
                    "symbol": ticker,
                    "provider": self._openbb_price_provider,
                    "start_date": start_date,
                    "end_date": end_date,
                },
                timeout=min(self._timeout, 15.0),
            )
        except requests.RequestException as exc:
            logger.warning("OpenBB price fallback failed for %s: %s", ticker, exc)
            return None

        if resp.status_code >= 400:
            logger.warning("OpenBB price fallback for %s returned %d", ticker, resp.status_code)
            return None

        try:
            payload = resp.json()
        except ValueError as exc:
            logger.warning("OpenBB price fallback returned non-JSON for %s: %s", ticker, exc)
            return None

        rows = payload.get("results")
        if not isinstance(rows, list):
            return None

        prices: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            date_value = row.get("date") or row.get("time")
            if date_value is None or any(row.get(field) is None for field in ("open", "close", "high", "low")):
                continue
            time_value = str(date_value)
            if "T" not in time_value:
                time_value = f"{time_value[:10]}T00:00:00"
            try:
                volume = int(row.get("volume") or 0)
            except (TypeError, ValueError):
                volume = 0
            prices.append(
                {
                    "open": float(row["open"]),
                    "close": float(row["close"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "volume": volume,
                    "time": time_value,
                }
            )

        if prices:
            logger.info(
                "Using OpenBB %s price fallback for %s (%d bars)",
                self._openbb_price_provider,
                ticker,
                len(prices),
            )
        return prices

    def _request(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> requests.Response | None:
        """HTTP request with retry on 429. Never raises."""
        url = self.BASE_URL + path
        for attempt, delay in enumerate((*self._RETRY_DELAYS, None)):
            try:
                resp = self._session.request(
                    method, url, timeout=self._timeout, **kwargs,
                )
            except requests.RequestException as exc:
                logger.warning("Request error on %s %s: %s", method, path, exc)
                return None

            if resp.status_code == 429 and delay is not None:
                logger.info(
                    "Rate limited (429), retrying in %ds (attempt %d/%d)",
                    delay, attempt + 1, len(self._RETRY_DELAYS),
                )
                time.sleep(delay)
                continue

            if resp.status_code >= 400:
                logger.warning("%s %s returned %d", method, path, resp.status_code)
                return None

            return resp

        logger.warning(
            "Rate limit exhausted after %d retries on %s %s",
            len(self._RETRY_DELAYS), method, path,
        )
        return None

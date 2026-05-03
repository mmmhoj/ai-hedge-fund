from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import pytest

from src.tools.api_kr import get_company_news_kr


def naver_html(rows):
    article_rows = "\n".join(
        f"""
        <tr>
            <td class="title"><a href="{href}" title="{title}">{title}</a></td>
            <td class="info">{source}</td>
            <td class="date">{date}</td>
        </tr>
        """
        for title, source, date, href in rows
    )
    return f"""
    <html>
        <body>
            <table summary="종목뉴스">
                <tbody>{article_rows}</tbody>
            </table>
        </body>
    </html>
    """


def response(html: str, status_code: int = 200) -> Mock:
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = html
    mock_response.content = html.encode("utf-8")
    return mock_response


def test_get_company_news_kr_parses_naver_html(monkeypatch):
    html = naver_html(
        [
            (
                "Samsung launches AI memory",
                "Yonhap",
                "2026.05.01 09:30",
                "/item/news_read.naver?article_id=1&office_id=001&code=005930",
            ),
            (
                "Samsung reports earnings",
                "Maeil",
                "2026.04.15 13:05",
                "/item/news_read.naver?article_id=2&office_id=009&code=005930",
            ),
            (
                "Samsung expands foundry",
                "Hankyung",
                "2026.04.01 08:00",
                "/item/news_read.naver?article_id=3&office_id=015&code=005930",
            ),
        ]
    )

    empty_html = "<html><body><table summary='종목뉴스'><tbody></tbody></table></body></html>"

    def fake_get(url, *args, **kwargs):
        page = int(parse_qs(urlparse(url).query)["page"][0])
        return response(html if page == 1 else empty_html)

    monkeypatch.setattr("requests.get", fake_get)

    news = get_company_news_kr("005930", "2026-05-01", start_date="2026-04-01", limit=100)

    assert len(news) == 3
    assert [item.title for item in news] == [
        "Samsung launches AI memory",
        "Samsung reports earnings",
        "Samsung expands foundry",
    ]
    assert [item.source for item in news] == ["Yonhap", "Maeil", "Hankyung"]
    assert [item.date for item in news] == [
        "2026-05-01T09:30:00+09:00",
        "2026-04-15T13:05:00+09:00",
        "2026-04-01T08:00:00+09:00",
    ]


def test_get_company_news_kr_respects_date_range(monkeypatch):
    html = naver_html(
        [
            ("After End", "Source", "2026.05.02 08:00", "/item/news_read.naver?article_id=1&code=005930"),
            ("In End", "Source", "2026.05.01 16:00", "/item/news_read.naver?article_id=2&code=005930"),
            ("In Middle", "Source", "2026.04.15 09:00", "/item/news_read.naver?article_id=3&code=005930"),
            ("In Start", "Source", "2026.04.01 00:01", "/item/news_read.naver?article_id=4&code=005930"),
            ("Before Start", "Source", "2026.03.31 23:59", "/item/news_read.naver?article_id=5&code=005930"),
        ]
    )

    empty_html = "<html><body><table summary='종목뉴스'><tbody></tbody></table></body></html>"

    def fake_get(url, *args, **kwargs):
        page = int(parse_qs(urlparse(url).query)["page"][0])
        return response(html if page == 1 else empty_html)

    monkeypatch.setattr("requests.get", fake_get)

    news = get_company_news_kr("005930", "2026-05-01", start_date="2026-04-01", limit=100)

    assert [item.title for item in news] == ["In End", "In Middle", "In Start"]


def test_get_company_news_kr_respects_limit(monkeypatch):
    html = naver_html(
        [
            (
                f"News {idx}",
                "Source",
                f"2026.04.{30 - idx:02d} 09:00",
                f"/item/news_read.naver?article_id={idx}&code=005930",
            )
            for idx in range(10)
        ]
    )

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: response(html))

    news = get_company_news_kr("005930", "2026-04-30", start_date="2026-04-01", limit=3)

    assert len(news) == 3
    assert [item.title for item in news] == ["News 0", "News 1", "News 2"]


def test_get_company_news_kr_paginates_until_start_date_reached(monkeypatch):
    pages = {
        1: naver_html(
            [
                ("P1 1", "Source", "2026.04.29 09:00", "/item/news_read.naver?article_id=11&code=005930"),
                ("P1 2", "Source", "2026.04.28 09:00", "/item/news_read.naver?article_id=12&code=005930"),
                ("P1 3", "Source", "2026.04.27 09:00", "/item/news_read.naver?article_id=13&code=005930"),
                ("P1 4", "Source", "2026.04.26 09:00", "/item/news_read.naver?article_id=14&code=005930"),
                ("P1 5", "Source", "2026.04.25 09:00", "/item/news_read.naver?article_id=15&code=005930"),
            ]
        ),
        2: naver_html(
            [
                ("P2 1", "Source", "2026.04.24 09:00", "/item/news_read.naver?article_id=21&code=005930"),
                ("P2 2", "Source", "2026.04.23 09:00", "/item/news_read.naver?article_id=22&code=005930"),
                ("P2 3", "Source", "2026.04.22 15:00", "/item/news_read.naver?article_id=23&code=005930"),
                ("P2 4", "Source", "2026.04.22 09:00", "/item/news_read.naver?article_id=24&code=005930"),
                ("P2 Old", "Source", "2026.04.15 09:00", "/item/news_read.naver?article_id=25&code=005930"),
            ]
        ),
    }
    calls = []

    def fake_get(url, *args, **kwargs):
        page = int(parse_qs(urlparse(url).query)["page"][0])
        calls.append(page)
        if page == 3:
            pytest.fail("page 3 should not be requested")
        return response(pages[page])

    monkeypatch.setattr("requests.get", fake_get)

    news = get_company_news_kr("005930", "2026-04-29", start_date="2026-04-22", limit=100)

    assert calls == [1, 2]
    assert len(news) == 9
    assert [item.title for item in news][-4:] == ["P2 1", "P2 2", "P2 3", "P2 4"]
    assert "P2 Old" not in [item.title for item in news]


def test_get_company_news_kr_empty_html_returns_empty(monkeypatch):
    monkeypatch.setattr(
        "requests.get",
        lambda *args, **kwargs: response("<html><body>No table</body></html>"),
    )

    assert get_company_news_kr("005930", "2026-05-01", start_date="2026-04-01", limit=100) == []


def test_get_company_news_kr_naver_blocks_returns_empty(monkeypatch):
    monkeypatch.setattr(
        "requests.get",
        lambda *args, **kwargs: response("<html></html>", status_code=403),
    )

    assert get_company_news_kr("005930", "2026-05-01", start_date="2026-04-01", limit=100) == []

    def blocked(*args, **kwargs):
        raise RuntimeError("blocked")

    monkeypatch.setattr("requests.get", blocked)

    assert get_company_news_kr("005930", "2026-05-01", start_date="2026-04-01", limit=100) == []


def test_get_company_news_kr_evidence_bundle_short_circuit(monkeypatch):
    bundled_row = {
        "ticker": "005930",
        "title": "Bundled news",
        "author": None,
        "source": "Fixture",
        "date": "2026-04-01T09:00:00+09:00",
        "url": "https://example.com/news",
        "sentiment": None,
    }
    bundle = {"company_news": {"005930": [bundled_row]}}

    def fail_request(*args, **kwargs):
        pytest.fail("network fetch should not be called")

    monkeypatch.setattr("requests.get", fail_request)

    news = get_company_news_kr(
        "005930",
        "2026-05-01",
        start_date="2026-04-01",
        limit=100,
        evidence_bundle=bundle,
    )

    assert [item.model_dump() for item in news] == [bundled_row]

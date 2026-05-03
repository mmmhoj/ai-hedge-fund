import re

KR_TICKER_PATTERN = re.compile(r"^\d{6}$")


def is_korean_ticker(ticker: str) -> bool:
    return bool(ticker) and bool(KR_TICKER_PATTERN.match(ticker))

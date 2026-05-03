from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

import requests

LIVE_BASE_URL = "https://openapi.koreainvestment.com:9443"
SANDBOX_BASE_URL = "https://openapivts.koreainvestment.com:29443"
REQUEST_TIMEOUT = 30
TOKEN_REFRESH_SKEW = dt.timedelta(minutes=5)


class KisError(Exception):
    pass


class KisClient:
    def __init__(
        self,
        app_key: str | None = None,
        app_secret: str | None = None,
        use_sandbox: bool | None = None,
    ) -> None:
        self.app_key = app_key or os.environ.get("KIS_APP_KEY", "")
        self.app_secret = app_secret or os.environ.get("KIS_APP_SECRET", "")
        if use_sandbox is None:
            self.use_sandbox = _env_bool("KIS_USE_SANDBOX", default=True)
        else:
            self.use_sandbox = use_sandbox

    def _base_url(self) -> str:
        return SANDBOX_BASE_URL if self.use_sandbox else LIVE_BASE_URL

    def _token_cache_path(self) -> Path:
        app_key = self._require_credentials()[0]
        key_prefix = "".join(
            char for char in app_key[:8] if char.isalnum() or char in {"-", "_"}
        )
        return Path.home() / ".cache" / "kis" / f"token-{key_prefix or 'unknown'}.json"

    def _load_cached_token(self) -> str | None:
        path = self._token_cache_path()
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            token = data.get("access_token")
            expires_at = _parse_datetime(data.get("expires_at"))
        except Exception:
            return None

        if not token or expires_at is None:
            return None
        if expires_at <= _utc_now() + TOKEN_REFRESH_SKEW:
            return None
        return str(token)

    def _save_token(self, token: str, expires_at: dt.datetime) -> None:
        path = self._token_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "access_token": token,
            "expires_at": _ensure_aware(expires_at).isoformat(),
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        path.chmod(0o600)

    def _request_new_token(self) -> tuple[str, dt.datetime]:
        app_key, app_secret = self._require_credentials()
        response = requests.post(
            f"{self._base_url()}/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey": app_key,
                "appsecret": app_secret,
            },
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            raise KisError(
                f"KIS token request failed: HTTP {response.status_code} {response.text[:500]}"
            )

        try:
            data = response.json()
        except ValueError as e:
            raise KisError(f"KIS token response was not JSON: {e}") from e

        token = data.get("access_token")
        expires_in = data.get("expires_in")
        if not token or expires_in is None:
            raise KisError("KIS token response missing access_token or expires_in")

        try:
            expires_at = _utc_now() + dt.timedelta(seconds=int(expires_in))
        except (TypeError, ValueError) as e:
            raise KisError(f"KIS token response has invalid expires_in: {expires_in}") from e

        return str(token), expires_at

    def access_token(self) -> str:
        self._require_credentials()
        cached = self._load_cached_token()
        if cached:
            return cached

        token, expires_at = self._request_new_token()
        self._save_token(token, expires_at)
        return token

    def get(self, path: str, *, tr_id: str, params: dict) -> dict:
        app_key, app_secret = self._require_credentials()
        response = requests.get(
            f"{self._base_url()}{path}",
            headers={
                "authorization": f"Bearer {self.access_token()}",
                "appkey": app_key,
                "appsecret": app_secret,
                "tr_id": tr_id,
                "custtype": "P",
            },
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            raise KisError(f"KIS request failed: HTTP {response.status_code} {response.text[:500]}")

        try:
            data = response.json()
        except ValueError as e:
            raise KisError(f"KIS response was not JSON: {e}") from e

        if not isinstance(data, dict):
            raise KisError("KIS response was not a JSON object")

        rt_cd = data.get("rt_cd")
        if rt_cd not in (None, "0", 0):
            msg = data.get("msg1") or data.get("msg_cd") or "unknown KIS error"
            raise KisError(f"KIS API error: {msg}")
        if "output" not in data:
            raise KisError("KIS response missing output")

        return data

    def _require_credentials(self) -> tuple[str, str]:
        if not self.app_key:
            raise KisError("Missing required env var: KIS_APP_KEY")
        if not self.app_secret:
            raise KisError("Missing required env var: KIS_APP_SECRET")
        return self.app_key, self.app_secret


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "f", "no", "n", "off"}


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _ensure_aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _parse_datetime(value: Any) -> dt.datetime | None:
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return _ensure_aware(parsed)

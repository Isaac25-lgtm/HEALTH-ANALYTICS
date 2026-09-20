from __future__ import annotations

import time
from collections.abc import Callable
from types import TracebackType
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.integrations.dhis2.errors import (
    Dhis2AuthError,
    Dhis2BoundExceededError,
    Dhis2CancelledError,
    Dhis2NotConfiguredError,
    Dhis2TimeoutError,
    Dhis2TransientError,
    Dhis2ValidationError,
)
from app.integrations.dhis2.redaction import RedactingLogger, safe_url
from app.services.observability import record_operational_event

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
logger = RedactingLogger()


class Dhis2HttpClient:
    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        basic_auth: tuple[str, str] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._sleep = sleep or time.sleep
        self._cancelled = cancelled or (lambda: False)
        self.last_retry_count = 0
        self._owns_client = True
        auth: httpx.Auth | None = None
        headers = {"Accept": "application/json"}
        if basic_auth is not None:
            auth = httpx.BasicAuth(*basic_auth)
        elif self.settings.dhis2_auth_method == "pat" and self.settings.dhis2_pat:
            headers["Authorization"] = f"ApiToken {self.settings.dhis2_pat}"
        elif self.settings.dhis2_username:
            auth = httpx.BasicAuth(self.settings.dhis2_username, self.settings.effective_dhis2_password)
        self._client = httpx.Client(
            base_url=self.settings.dhis2_base_url.rstrip("/"),
            auth=auth,
            headers=headers,
            timeout=self.settings.dhis2_timeout_seconds,
            transport=transport,
            follow_redirects=True,
        )
        self._has_basic_auth_override = basic_auth is not None

    def __enter__(self) -> Dhis2HttpClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def configured(self) -> bool:
        return bool(
            self.settings.dhis2_base_url
            and (
                (self.settings.dhis2_auth_method == "pat" and self.settings.dhis2_pat)
                or self._has_basic_auth_override
                or self.settings.dhis2_username
            )
        )

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if not self.configured():
            raise Dhis2NotConfiguredError()
        retries = 0
        last_error: Exception | None = None
        started = time.perf_counter()
        while retries <= self.settings.dhis2_max_retries:
            if self._cancelled():
                raise Dhis2CancelledError()
            try:
                response = self._client.request(method, path, **kwargs)
            except httpx.TimeoutException as exc:
                last_error = Dhis2TimeoutError()
                retries += 1
                self.last_retry_count = retries
                if retries > self.settings.dhis2_max_retries:
                    raise last_error from exc
                self._backoff(retries, retry_after=None)
                continue
            except httpx.HTTPError as exc:
                last_error = Dhis2TransientError("DHIS2 request failed.")
                retries += 1
                self.last_retry_count = retries
                if retries > self.settings.dhis2_max_retries:
                    raise last_error from exc
                self._backoff(retries, retry_after=None)
                continue

            if len(response.content) > self.settings.dhis2_max_response_bytes:
                raise Dhis2BoundExceededError()
            if response.status_code in {401, 403}:
                logger.error(
                    "DHIS2 authentication failed",
                    status=response.status_code,
                    url=safe_url(str(response.url)),
                )
                raise Dhis2AuthError()
            if response.status_code in RETRYABLE_STATUS:
                retries += 1
                self.last_retry_count = retries
                last_error = Dhis2TransientError("DHIS2 returned a transient error.")
                if retries > self.settings.dhis2_max_retries:
                    raise last_error
                self._backoff(retries, retry_after=response.headers.get("Retry-After"))
                continue
            if response.status_code >= 400:
                raise Dhis2ValidationError("DHIS2 response failed validation.")
            duration_ms = int((time.perf_counter() - started) * 1000)
            record_operational_event(
                "connector_request",
                duration_ms=duration_ms,
                retry_count=retries,
                payload={"path": path, "status": response.status_code},
            )
            return response
        raise last_error or Dhis2TransientError()

    def get_json(self, path: str, params: dict | None = None) -> dict:
        response = self.request("GET", path, params=params)
        try:
            payload = response.json()
        except ValueError as exc:
            raise Dhis2ValidationError("Response is not JSON.") from exc
        if not isinstance(payload, dict):
            raise Dhis2ValidationError("JSON object expected.")
        return payload

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        delay = min(
            self.settings.dhis2_retry_base_seconds * (2 ** (attempt - 1)),
            self.settings.dhis2_retry_max_seconds,
        )
        if retry_after:
            try:
                delay = min(float(retry_after), self.settings.dhis2_retry_max_seconds)
            except ValueError:
                pass
        logger.warning("retrying DHIS2 request", attempt=attempt, delay_seconds=delay)
        if delay > 0:
            self._sleep(delay)

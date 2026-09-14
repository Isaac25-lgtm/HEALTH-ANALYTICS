"""Internal AI provider registry. Business services must not hard-code vendor SDKs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx


@dataclass(frozen=True)
class ProviderCompletion:
    text: str
    provider: str
    model: str | None
    token_usage: dict
    error_code: str | None = None
    statements: list | None = None


class AiProvider(Protocol):
    def complete(self, payload: dict, *, timeout: float) -> ProviderCompletion: ...


class HttpsJsonProvider:
    def __init__(self, *, name: str, base_url: str, api_key: str) -> None:
        self.name = name
        self.base_url = base_url
        self.api_key = api_key

    def complete(self, payload: dict, *, timeout: float) -> ProviderCompletion:
        if not self.base_url.startswith("https://"):
            return ProviderCompletion("", self.name, payload.get("model"), {}, "insecure_ai_endpoint")
        response = httpx.post(
            self.base_url.rstrip("/") + "/v1/generate",
            json=payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.json()
        statements = body.get("statements") if isinstance(body, dict) else None
        return ProviderCompletion(
            text=str(body.get("text") or ""),
            provider=self.name,
            model=payload.get("model"),
            token_usage=body.get("usage") or {},
            statements=statements if isinstance(statements, list) else None,
        )


_REGISTRY: dict[str, type[HttpsJsonProvider]] = {"https_json": HttpsJsonProvider}


def resolve_provider(name: str, *, base_url: str, api_key: str) -> AiProvider:
    cls = _REGISTRY.get(name or "https_json", HttpsJsonProvider)
    return cls(name=name or "configured", base_url=base_url, api_key=api_key)

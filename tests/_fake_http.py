"""Fake aiohttp primitives used by client unit tests."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
from typing import Any

from yarl import URL


@dataclass(slots=True)
class StubResponse:
    """Stubbed HTTP response payload."""

    status: int
    payload: Any
    url: str
    headers: dict[str, str] | None = None


class FakeClientResponse:
    """Subset of aiohttp.ClientResponse used by the API client."""

    def __init__(self, stub: StubResponse) -> None:
        self.status = stub.status
        self._payload = stub.payload
        self.url = URL(stub.url)
        self.headers = stub.headers or {}

    async def json(self, content_type: str | None = None) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    async def text(self) -> str:
        if isinstance(self._payload, (dict, list)):
            return json.dumps(self._payload)
        return str(self._payload)


class _FakeContextManager:
    """Async context manager wrapper around fake response."""

    def __init__(self, response: FakeClientResponse) -> None:
        self._response = response

    async def __aenter__(self) -> FakeClientResponse:
        return self._response

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class FakeClientSession:
    """Minimal request dispatcher compatible with aiohttp.ClientSession."""

    def __init__(self, routes: dict[tuple[str, str], list[StubResponse]]) -> None:
        self._routes = defaultdict(list)
        for key, responses in routes.items():
            self._routes[(key[0].upper(), key[1])] = list(responses)
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeContextManager:
        method = method.upper()
        path = URL(url).path
        key = (method, path)
        self.calls.append(key)

        if key not in self._routes or not self._routes[key]:
            raise AssertionError(f"Unexpected request: {key}")

        stub = self._routes[key].pop(0)
        return _FakeContextManager(FakeClientResponse(stub))

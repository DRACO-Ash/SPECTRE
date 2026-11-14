"""A stand-in UDL for route tests: httpx's own MockTransport, so nothing leaves the process.

The routes build their client as ``httpx.AsyncClient(...)``. :meth:`UdlStub.install`
swaps that constructor for one that keeps every argument the route passed and
adds a transport answering from :attr:`UdlStub.answer`, so the request a route
sends is the real one: URL, query string and Basic auth header as built.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any

import httpx
import pytest

Answer = Callable[[httpx.Request], httpx.Response]


def reply(payload: Any = None, *, status: int = 200, text: str | None = None) -> Answer:
    """An answer of *payload* as JSON, or of *text* verbatim, with *status*."""
    def answer(_request: httpx.Request) -> httpx.Response:
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=payload)
    return answer


def fails_with(exc: Exception) -> Answer:
    """An answer that never comes: *exc* raised as the transport would."""
    def answer(_request: httpx.Request) -> httpx.Response:
        raise exc
    return answer


class UdlStub:
    """Answers every UDL GET with :attr:`answer` and records each request."""

    def __init__(self, answer: Answer | None = None) -> None:
        self.answer: Answer = answer or reply([])
        self.requests: list[httpx.Request] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.answer(request)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> UdlStub:
        real = httpx.AsyncClient
        transport = httpx.MockTransport(self._handle)
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real(transport=transport, **kwargs))
        return self

    @property
    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]

    def params(self, index: int = -1) -> dict[str, str]:
        return dict(self.requests[index].url.params)

    def credential(self, index: int = -1) -> str:
        """The ``user:password`` the request carried as Basic auth."""
        scheme, _, token = self.requests[index].headers["authorization"].partition(" ")
        assert scheme == "Basic"
        return base64.b64decode(token).decode()

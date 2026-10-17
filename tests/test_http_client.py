"""Politeness tests: robots.txt, retries and backoff, using a fake network."""

from __future__ import annotations

import httpx
import pytest

from price_tracker.http_client import FetchError, PoliteClient, RobotsDisallowedError

BASE = "https://example.test/"


def make_client(handler, **kwargs) -> tuple[PoliteClient, list[float]]:
    """Client wired to a fake transport; returns it plus a list of the sleeps it asked for."""
    sleeps: list[float] = []
    client = PoliteClient(BASE, transport=httpx.MockTransport(handler),
                          sleep=sleeps.append, delay=0, **kwargs)
    return client, sleeps


def test_sends_user_agent() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["User-Agent"])
        return httpx.Response(404 if request.url.path == "/robots.txt" else 200, text="ok")

    client, _ = make_client(handler, user_agent="test-bot/1.0")
    client.get_html(BASE + "page.html")
    assert seen == ["test-bot/1.0", "test-bot/1.0"]


def test_robots_disallow_is_obeyed() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        return httpx.Response(200, text="ok")

    client, _ = make_client(handler)
    assert client.get_html(BASE + "public.html") == b"ok"
    with pytest.raises(RobotsDisallowedError):
        client.get_html(BASE + "private/secret.html")
    assert "/private/secret.html" not in requested  # never even requested


def test_robots_crawl_delay_raises_our_delay() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="User-agent: *\nCrawl-delay: 5\n")

    client, _ = make_client(handler)
    assert client.delay == 5


def test_retries_server_errors_with_exponential_backoff() -> None:
    responses = iter([503, 500, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(next(responses), text="finally")

    client, sleeps = make_client(handler, backoff_base=1.0)
    assert client.get_html(BASE + "flaky.html") == b"finally"
    assert sleeps == [1.0, 2.0]


def test_honours_retry_after_header() -> None:
    responses = iter([httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200)])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404) if request.url.path == "/robots.txt" else next(responses)

    client, sleeps = make_client(handler)
    client.get_html(BASE + "busy.html")
    assert sleeps == [7.0]


def test_retries_network_errors_then_gives_up() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        attempts += 1
        raise httpx.ConnectError("connection refused")

    client, sleeps = make_client(handler, max_retries=2)
    with pytest.raises(FetchError):
        client.get_html(BASE + "down.html")
    assert attempts == 3  # first try + 2 retries
    assert sleeps == [1.0, 2.0]


def test_404_is_not_retried() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.path != "/robots.txt":
            attempts += 1
        return httpx.Response(404)

    client, _ = make_client(handler)
    with pytest.raises(FetchError, match="HTTP 404"):
        client.get_html(BASE + "missing.html")
    assert attempts == 1


def test_waits_between_requests() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404 if request.url.path == "/robots.txt" else 200)

    sleeps: list[float] = []
    client = PoliteClient(BASE, transport=httpx.MockTransport(handler), sleep=sleeps.append, delay=2.0)
    client.get_html(BASE + "a.html")
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 2.0  # robots.txt -> a.html gap
